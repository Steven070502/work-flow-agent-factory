"""
流水线MultiAgent Mock测试
不需要真实API Key，模拟完整执行流程
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xxn_universal_agent.agents.agent import GlobalMemory, LeaderAgent, SubAgent, PipelineExecutor, SingleAgent, VerifierAgent
from xxn_universal_agent.tools.tools import create_default_registry


class MockLLM:
    """模拟LLM，不需要真实API"""

    def __init__(self):
        self.call_count = 0

    def chat(self, messages: list) -> str:
        self.call_count += 1
        content = messages[-1]["content"]
        system = str(messages[0].get("content", ""))

        if "PlanVerifier" in system:
            return '{"verdict": "pass", "score": 96, "issues": [], "required_fixes": [], "feedback": ""}'

        if "StepVerifier" in system:
            return '{"verdict": "pass", "score": 94, "issues": [], "required_fixes": [], "feedback": ""}'

        if "FinalVerifier" in system:
            return '{"verdict": "pass", "score": 95, "issues": [], "required_fixes": [], "feedback": ""}'

        if "FinalSynthesisAgent" in system:
            return '{"type": "final_answer", "answer": "综合投资结论：新能源汽车市场仍处于增长期，头部集中和智能化升级是主线。基于销量、市占率、技术趋势和风险，建议重点关注比亚迪、宁德时代和智能化供应链，同时警惕价格战、出海政策和技术路线变化。"}'

        # 模拟LeaderAgent的plan
        if "拆解" in content or "Leader" in system:
            return '{"analysis": "新能源汽车市场处于快速增长期，需从数据、趋势、投资建议三维度分析", "pipeline": [{"id": 1, "role": "数据研究员", "task": "搜索2024年新能源汽车销量和市场份额数据", "input_from": null, "output_to": 2}, {"id": 2, "role": "行业分析师", "task": "分析销量趋势、竞争格局和技术路线", "input_from": 1, "output_to": 3}, {"id": 3, "role": "投资顾问", "task": "基于数据分析给出投资建议和风险提示", "input_from": 2, "output_to": null}]}'

        # 模拟SubAgent-1（研究员）
        if "你是团队中的【数据研究员】" in system:
            return '{"type": "final_answer", "answer": "【2024年Q1-Q3数据】\\n1. 比亚迪：销量280万辆，市占率35%（同比+28%）\\n2. 特斯拉：销量120万辆，市占率15%（同比+8%）\\n3. 理想/蔚来/小鹏：合计占比12%\\n4. 整体市场渗透率：42%（2023年为31%）\\n5. 电池成本下降15%，推动价格带下移"}'

        # 模拟SubAgent-2（分析师）
        if "你是团队中的【行业分析师】" in system:
            return '{"type": "final_answer", "answer": "【趋势分析】\\n1. 头部集中：比亚迪+特斯拉占50%，马太效应明显\\n2. 技术分化：磷酸铁锂（成本型）vs 固态电池（高端型）\\n3. 出海加速：东南亚和欧洲成为主要增量市场\\n4. 智能化竞争：自动驾驶从L2向L3过渡，华为/小鹏领先\\n5. 价格战趋缓：20万以下市场红海，30万以上蓝海"}'

        # 模拟SubAgent-3（投资顾问）
        if "你是团队中的【投资顾问】" in system:
            return '{"type": "final_answer", "answer": "【投资建议】\\n✅ 看好标的：比亚迪（全产业链+出海）、宁德时代（电池龙头）、华为智选车（智能化溢价）\\n⚠️ 风险提示：价格战压缩毛利率、地缘政治影响出海、固态电池技术路线不确定性\\n💡 策略建议：短期关注电池供应链（降本受益），中期关注智能化零部件（L3渗透），长期关注固态电池技术突破"}'

        # 模拟SingleAgent
        if "计算" in content or "数学" in content:
            return '{"type": "final_answer", "answer": "结果是 56088"}'

        return '{"type": "final_answer", "answer": "【Mock结果】这是模拟输出，用于验证架构流程"}'

    def info(self):
        return {"provider": "mock", "model": "test-model", "base_url": "localhost"}


class StepReviseMockLLM(MockLLM):
    """第一次Step检查要求返工，第二次通过。"""

    def __init__(self):
        super().__init__()
        self.step_verify_calls = 0
        self.researcher_calls = 0

    def chat(self, messages: list) -> str:
        system = str(messages[0].get("content", ""))
        if "StepVerifier" in system:
            self.step_verify_calls += 1
            if self.step_verify_calls == 1:
                return '{"verdict": "revise", "score": 55, "issues": ["缺少具体销量数据"], "required_fixes": ["补充数字和结论"], "feedback": "请补充具体销量、市占率和趋势，不要只写已完成。"}'
            return '{"verdict": "pass", "score": 90, "issues": [], "required_fixes": [], "feedback": ""}'

        if "你是团队中的【数据研究员】" in system:
            self.call_count += 1
            self.researcher_calls += 1
            if self.researcher_calls == 1:
                return '{"type": "final_answer", "answer": "已完成数据收集。"}'
            return '{"type": "final_answer", "answer": "【修订后数据】比亚迪销量280万辆、市占率35%；特斯拉销量120万辆、市占率15%；整体渗透率42%，可供下游分析。"}'

        return super().chat(messages)


def test_pipeline():
    """测试完整流水线"""
    print("=" * 70)
    print("🧪 Mock测试：流水线MultiAgent")
    print("=" * 70)

    llm = MockLLM()
    tools = create_default_registry()
    pipeline = PipelineExecutor(
        llm,
        tools,
        enable_plan_verifier=True,
        enable_step_verifier=True,
        enable_final_verifier=True,
        max_verify_retries=1,
    )

    result = pipeline.run("分析一下新能源汽车市场，给出投资建议")

    print(f"\n{'='*70}")
    print("📊 测试统计")
    print(f"{'='*70}")
    print(f"LLM调用次数: {llm.call_count}")
    print(f"GlobalMemory结果数: {len(pipeline.global_memory.results)}")
    print(f"执行状态: {pipeline.global_memory.status}")
    assert pipeline.global_memory.status == "completed", "流水线状态应为completed"
    assert len(pipeline.global_memory.results) == 3, "应保存3个Step结果"
    assert "综合投资结论" in result, "最终输出应来自FinalSynthesisAgent"
    assert not result.startswith("# 任务完成报告"), "最终输出不应只是GlobalMemory机械拼接"

    # 验证记忆互通
    print(f"\n{'='*70}")
    print("🔍 记忆互通验证")
    print(f"{'='*70}")

    gm = pipeline.global_memory
    print(f"✅ 原始任务已保存: {gm.original_task[:40]}...")
    print(f"✅ Leader分析已保存: {gm.leader_analysis[:40]}...")
    print(f"✅ Step1结果已保存: {gm.get_result(1)[:50]}...")
    print(f"✅ Step2结果已保存: {gm.get_result(2)[:50]}...")
    print(f"✅ Step3结果已保存: {gm.get_result(3)[:50]}...")

    # 验证前置结果传递
    print(f"\n{'='*70}")
    print("🔗 前置结果传递验证")
    print(f"{'='*70}")
    step2_ok = "销量" in gm.get_previous_result(2)
    step3_ok = "趋势" in gm.get_previous_result(3)
    print(f"Step2的前置结果来自Step1: {step2_ok}")
    print(f"Step3的前置结果来自Step2: {step3_ok}")
    assert step2_ok, "Step2没有收到Step1的具体交付物"
    assert step3_ok, "Step3没有收到Step2的具体交付物"
    assert "【投资建议】" in gm.get_result(3), "最后一步应输出投资建议"
    assert any(r["stage"] == "plan" and r["verdict"] == "pass" for r in gm.verifier_records), "PlanVerifier应通过"
    assert any(r["stage"] == "step_1" and r["verdict"] == "pass" for r in gm.verifier_records), "StepVerifier应通过"
    assert any(r["stage"] == "final" and r["verdict"] == "pass" for r in gm.verifier_records), "FinalVerifier应通过"

    print(f"\n{'='*70}")
    print("✅ 流水线Mock测试通过")
    print(f"{'='*70}")


def test_verifier_agent_pass():
    """测试PlanVerifier/StepVerifier基础pass解析"""
    print("\n" + "=" * 70)
    print("🧪 Mock测试：VerifierAgent")
    print("=" * 70)

    llm = MockLLM()
    plan_verifier = VerifierAgent(llm, "plan")
    verdict = plan_verifier.verify(
        original_task="分析新能源汽车市场",
        leader_analysis="需要分步骤分析",
        pipeline=[{"id": 1, "role": "研究员", "task": "收集数据", "input_from": None, "output_to": None}],
    )
    assert verdict["verdict"] == "pass", "PlanVerifier应返回pass"
    assert verdict["score"] >= 90, "PlanVerifier分数应被正确解析"

    step_verifier = VerifierAgent(llm, "step")
    verdict = step_verifier.verify(
        original_task="分析新能源汽车市场",
        current_step={"id": 1, "role": "研究员", "task": "收集数据"},
        current_output="具体数据结果",
    )
    assert verdict["verdict"] == "pass", "StepVerifier应返回pass"
    print("✅ VerifierAgent测试通过")


def test_step_verifier_revise_retry():
    """测试StepVerifier要求返工后，同一SubAgent重试成功。"""
    print("\n" + "=" * 70)
    print("🧪 Mock测试：StepVerifier revise后重试")
    print("=" * 70)

    llm = StepReviseMockLLM()
    tools = create_default_registry()
    pipeline = PipelineExecutor(
        llm,
        tools,
        enable_plan_verifier=True,
        enable_step_verifier=True,
        enable_final_verifier=True,
        max_verify_retries=2,
    )
    result = pipeline.run("分析一下新能源汽车市场，给出投资建议")

    records = pipeline.global_memory.verifier_records
    step1_records = [r for r in records if r["stage"] == "step_1"]
    assert len(step1_records) >= 2, "Step1应至少经历一次返工和一次通过"
    assert step1_records[0]["verdict"] == "revise", "第一次StepVerifier应要求返工"
    assert step1_records[-1]["verdict"] == "pass", "返工后StepVerifier应通过"
    assert llm.researcher_calls >= 2, "SubAgent应被重试"
    assert "综合投资结论" in result, "返工后仍应生成最终综合答案"
    print("✅ StepVerifier revise重试测试通过")


def test_verifier_disabled_by_default():
    """默认关闭Verifier，但保留FinalSynthesis最终综合。"""
    print("\n" + "=" * 70)
    print("🧪 Mock测试：默认关闭Verifier")
    print("=" * 70)

    llm = MockLLM()
    tools = create_default_registry()
    pipeline = PipelineExecutor(llm, tools)
    result = pipeline.run("分析一下新能源汽车市场，给出投资建议")

    assert pipeline.enable_plan_verifier is False
    assert pipeline.enable_step_verifier is False
    assert pipeline.enable_final_verifier is False
    assert pipeline.global_memory.verifier_records == [], "默认关闭时不应产生Verifier记录"
    assert "综合投资结论" in result, "关闭Verifier时仍应使用FinalSynthesis"
    print("✅ 默认关闭Verifier测试通过")


def test_single_agent():
    """测试单Agent"""
    print("\n" + "=" * 70)
    print("🧪 Mock测试：SingleAgent")
    print("=" * 70)

    llm = MockLLM()
    tools = create_default_registry()
    agent = SingleAgent(llm, tools)

    result = agent.run("计算 123 * 456")
    print(f"\n📋 结果: {result}")
    print(f"✅ SingleAgent测试通过")


def test_global_memory():
    """测试GlobalMemory核心功能"""
    print("\n" + "=" * 70)
    print("🧪 Mock测试：GlobalMemory")
    print("=" * 70)

    gm = GlobalMemory()
    gm.set_task("分析AI行业")
    gm.set_leader_plan("AI处于爆发期", [
        {"id": 1, "role": "研究员", "task": "搜数据"},
        {"id": 2, "role": "分析师", "task": "做分析", "input_from": 1},
    ])

    gm.save_result(1, "数据结果A")
    gm.save_result(2, "分析结果B")

    ctx = gm.get_global_context(2)
    print(f"\nStep2收到的全局上下文:")
    print(ctx[:500] + "...")

    prev = gm.get_previous_result(2)
    print(f"\nStep2的前置结果: {prev}")
    assert prev == "数据结果A", "前置结果传递失败"

    print("\n✅ GlobalMemory测试通过")


if __name__ == "__main__":
    test_global_memory()
    test_single_agent()
    test_verifier_agent_pass()
    test_verifier_disabled_by_default()
    test_step_verifier_revise_retry()
    test_pipeline()
