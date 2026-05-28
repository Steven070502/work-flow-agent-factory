"""
XXN Universal Agent Framework —— 主入口
支持: InputGuard输入分级 + 单Agent + 流水线MultiAgent

流水线MultiAgent架构:
    User → InputGuard → LeaderAgent（拆解流水线计划）
                              ↓
                    PipelineExecutor（串行执行）
                              ↓
        Step1 → Step2 → Step3 → ... → Final Report
          ↓        ↓        ↓
       结果存入GlobalMemory，下一步读取前置结果+全局上下文
"""

import os
import sys
import re

from dotenv import load_dotenv

from .core.llm import LLM
from .tools.tools import create_default_registry
from .agents.agent import SingleAgent, PipelineExecutor


# ── MockLLM：用于无Key测试 ──
class MockLLM:
    """模拟LLM，不需要真实API Key"""

    def __init__(self):
        self.call_count = 0

    def chat(self, messages: list) -> str:
        self.call_count += 1
        content = messages[-1].get("content", "")
        sys_content = messages[0].get("content", "") if messages else ""

        if "PlanVerifier" in sys_content:
            return '{"verdict": "pass", "score": 95, "issues": [], "required_fixes": [], "feedback": ""}'

        if "StepVerifier" in sys_content:
            return '{"verdict": "pass", "score": 92, "issues": [], "required_fixes": [], "feedback": ""}'

        if "FinalVerifier" in sys_content:
            return '{"verdict": "pass", "score": 94, "issues": [], "required_fixes": [], "feedback": ""}'

        if "FinalSynthesisAgent" in sys_content:
            return '{"type": "final_answer", "answer": "综合结论：如果2025年只能先学一门，优先推荐Python；若目标是3个月内快速做网页或找前端岗位，则JavaScript更合适。依据是Python在AI/数据方向薪资上限和增长趋势更强，JavaScript岗位数量更多但前端竞争更激烈。"}'

        # 先检查SubAgent当前角色。必须精确匹配当前Agent，避免被“上游角色名”误触发。
        if "你是团队中的【数据研究员】" in sys_content:
            return '{"type": "final_answer", "answer": "【2024年就业数据】\\n\\n**Python:**\\n- 平均年薪: 25-40万（一线城市）\\n- 岗位数量: Boss直聘约12万个相关岗位\\n- 热门方向: AI/大模型、数据分析、自动化运维、后端开发\\n- 增长趋势: AI岗位同比增长65%\\n\\n**JavaScript:**\\n- 平均年薪: 18-35万（一线城市）\\n- 岗位数量: Boss直聘约15万个相关岗位\\n- 热门方向: React/Vue前端、Node.js全栈、Electron桌面、React Native移动端\\n- 增长趋势: 全栈岗位增长40%，纯前端增长放缓至15%"}'

        if "你是团队中的【对比分析师】" in sys_content:
            return '{"type": "final_answer", "answer": "【对比分析】\\n\\n1. **薪资对比**: Python天花板更高（AI方向可达60万+），JS起薪略低但差距不大\\n2. **岗位数量**: JS岗位更多（15万 vs 12万），但Python高质量岗位增长更快\\n3. **技术方向**: \\n   - Python: AI/数据是核心壁垒，不可替代性强\\n   - JS: 生态最广（前端+后端+桌面+移动端），但内卷严重\\n4. **入门难度**: JS更容易出成果（可视化即时反馈），Python初期较枯燥\\n5. **长期趋势**: AI浪潮下Python价值持续上升，JS随Web3/AI应用扩展新场景"}'

        if "你是团队中的【职业顾问】" in sys_content:
            return '{"type": "final_answer", "answer": "【2025初学者选择建议】\\n\\n**选Python如果你:**\\n- 目标是AI/数据/算法/自动化（高薪赛道）\\n- 能承受6个月以上的学习曲线\\n- 有数学/逻辑基础\\n\\n**选JavaScript如果你:**\\n- 想快速看到成果（1个月就能做网页）\\n- 目标是全栈/前端/独立开发\\n- 喜欢即时反馈和视觉呈现\\n\\n**我的建议**: 如果2025年只能学一门，优先Python。AI时代Python是基础设施，JS可以后续补充。但如果急需找工作且时间有限（3个月内），先学JS更快上岗。"}'

        # 再检查LeaderAgent plan
        if "拆解" in content or "Leader" in sys_content:
            return '{"analysis": "Python在AI/数据领域强势，JS在Web前端主导，初学者选择需结合职业目标", "pipeline": [{"id": 1, "role": "数据研究员", "task": "搜索Python和JavaScript 2024年就业薪资、岗位数量、热门方向数据", "input_from": null, "output_to": 2}, {"id": 2, "role": "对比分析师", "task": "基于数据对比两者薪资、岗位、技术方向的差异和趋势", "input_from": 1, "output_to": 3}, {"id": 3, "role": "职业顾问", "task": "基于对比分析，结合初学者身份给出2025年语言选择建议", "input_from": 2, "output_to": null}]}'

        # SingleAgent fallback
        if "计算" in content:
            return '{"type": "final_answer", "answer": "56088"}'

        return '{"type": "final_answer", "answer": "【Mock结果】框架运行正常"}'

    def info(self):
        return {"provider": "mock", "model": "test-offline", "base_url": "localhost"}


# ═══════════════════════════════════════════════
# InputGuard —— 输入守卫（保留）
# ═══════════════════════════════════════════════

class InputGuard:
    """
    智能输入分级
    
    LEVEL1: 闲聊问候 → 直接回复，不走Agent
    LEVEL2: 简单问题 → SingleAgent单Agent处理
    LEVEL3: 复杂任务 → PipelineExecutor流水线MultiAgent处理
    """

    PROMPT = """判断用户输入属于哪个级别：

LEVEL1（纯闲聊/问候，直接回复）：你好、再见、谢谢、你是谁、今天天气
LEVEL2（普通问题，单Agent处理）：查价格、做计算、写代码、搜信息、简单问答
LEVEL3（复杂任务，需要多Agent流水线）：分析市场、制定策略、写报告、做调研、多步骤项目

用户输入：{input}

只输出 LEVEL1 / LEVEL2 / LEVEL3，不要其他内容："""

    def __init__(self, llm: LLM):
        self.llm = llm

    def _self_intro(self) -> str:
        """根据当前LLM实例动态生成一条轻量身份提示。"""
        info = self.llm.info() if hasattr(self.llm, "info") else {}
        provider = info.get("provider", "unknown")
        model = info.get("model", "unknown")
        return (
            "我是 XXN Universal Agent。"
            f"现在接入的是 {provider} 的 {model}。"
            "你直接提任务就行，我会按问题复杂度自己选择处理方式。"
        )

    def check(self, user_input: str) -> dict:
        user_input = user_input.strip()
        current_input = user_input
        marker = "【当前问题】"
        if marker in user_input:
            current_input = user_input.rsplit(marker, 1)[-1].strip()

        if not current_input or len(current_input) < 2:
            return {"pass": False, "level": "empty", "direct_response": "请输入具体的问题。"}

        # 简单规则只看当前问题，避免历史对话里的“你是谁”等触发词污染后续路由。
        self_intro_patterns = [
            r"介绍一下你自己",
            r"你是谁",
            r"你是什么模型",
            r"你用的什么模型",
            r"你能做什么",
        ]
        for p in self_intro_patterns:
            if re.search(p, current_input, re.IGNORECASE):
                return {"pass": False, "level": "chat", "direct_response": self._self_intro()}

        greeting_patterns = [
            r"^你好",
            r"^在吗",
            r"^hi$",
            r"^hello$",
            r"^谢谢",
            r"^再见",
        ]
        for p in greeting_patterns:
            if re.search(p, current_input, re.IGNORECASE):
                return {"pass": False, "level": "chat", "direct_response": self._self_intro()}

        # LLM判断只分类当前问题；历史上下文留给后续Agent回答时使用。
        messages = [
            {"role": "system", "content": "你是输入分类器，只输出LEVEL1、LEVEL2或LEVEL3。"},
            {"role": "user", "content": self.PROMPT.format(input=current_input)},
        ]

        try:
            raw = self.llm.chat(messages).strip().upper()

            if "LEVEL1" in raw:
                reply = self.llm.chat([
                    {"role": "system", "content": "你是智能助手，简洁回答用户。"},
                    {"role": "user", "content": user_input},
                ])
                return {"pass": False, "level": "chat", "direct_response": reply}

            elif "LEVEL2" in raw:
                return {"pass": True, "level": "simple", "direct_response": None}

            else:  # LEVEL3 或无法判断
                return {"pass": True, "level": "complex", "direct_response": None}

        except Exception as e:
            err = str(e)
            if "invalid_api_key" in err or "Incorrect API key" in err or "401" in err:
                raise RuntimeError("LLM API Key 无效，请检查 .env 中的 API_KEY / MODEL_PROVIDER / BASE_URL。") from e
            # 非认证类分类失败，默认按复杂任务处理
            return {"pass": True, "level": "complex", "direct_response": None}


# ═══════════════════════════════════════════════
# 主程序
# ═══════════════════════════════════════════════

def print_banner():
    print("=" * 60)
    print("🤖 XXN Universal Agent Framework")
    print("=" * 60)
    print("支持: InputGuard + 单Agent + 流水线MultiAgent")
    print("=" * 60)


def create_llm(use_mock: bool = False) -> LLM:
    """创建LLM实例，支持Mock模式"""
    if use_mock:
        print("\n🧪 Mock模式：使用模拟LLM（无需API Key）")
        return MockLLM()

    load_dotenv()
    try:
        llm = LLM()
        info = llm.info()
        print(f"\n✅ LLM加载成功 | {info['provider']} | {info['model']}")
        return llm
    except ValueError as e:
        print(f"\n⚠️ {e}")
        print("\n有两种选择:")
        print("  1. 创建 .env 填入真实API_KEY，然后重跑")
        print("  2. 加 --test 参数用Mock模式测试框架流程")
        print("\n示例: python main.py --test 或 xxn-agent --test")
        sys.exit(1)


def main():
    use_mock = "--test" in sys.argv
    if use_mock:
        sys.argv.remove("--test")
    print_banner()
    llm = create_llm(use_mock=use_mock)
    tools = create_default_registry()
    guard = InputGuard(llm)

    # 初始化Agent
    single_agent = SingleAgent(llm, tools)
    pipeline = PipelineExecutor(llm, tools)

    # 全局对话历史（跨轮次记忆）
    conversation_history = []

    print("\n输入你的任务，或 'q' 退出\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见")
            break

        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit", "退出"):
            print("👋 再见")
            break

        # 构建带历史上下文的输入
        if conversation_history:
            history_text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Agent'}: {m['content'][:200]}"
                for m in conversation_history[-6:]  # 最近3轮
            )
            full_input = f"【历史对话】\n{history_text}\n\n【当前问题】{user_input}"
        else:
            full_input = user_input

        # InputGuard判断（基于完整上下文）
        check = guard.check(full_input)

        if not check["pass"]:
            # LEVEL1: 直接回复
            print(f"\nAgent > {check['direct_response']}\n")
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": check['direct_response']})
            continue

        try:
            if check["level"] == "simple":
                # LEVEL2: 单Agent
                print("\n[模式: SingleAgent 简单处理]\n")
                # 把历史注入到任务中
                if conversation_history:
                    task_with_history = f"{full_input}\n\n注意：这是多轮对话，请参考上面的历史上下文回答。"
                else:
                    task_with_history = user_input
                result = single_agent.run(task_with_history)
                print(f"\n📋 结果:\n{result}\n")

            else:
                # LEVEL3: 流水线MultiAgent
                print("\n[模式: Pipeline MultiAgent 复杂任务]\n")
                if conversation_history:
                    task_with_history = f"{full_input}\n\n注意：这是多轮对话，请参考上面的历史上下文回答。"
                else:
                    task_with_history = user_input
                result = pipeline.run(task_with_history)
                print(f"\n{result}\n")

            # 保存到对话历史
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": result})

            # 防止历史过长
            if len(conversation_history) > 20:
                conversation_history = conversation_history[-20:]

        except Exception as e:
            print(f"\n❌ 执行出错: {e}\n")


if __name__ == "__main__":
    main()
