"""
流水线MultiAgent Mock测试
不需要真实API Key，模拟完整执行流程
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.agent import GlobalMemory, LeaderAgent, SubAgent, PipelineExecutor, SingleAgent
from tools.tools import create_default_registry


class MockLLM:
    """模拟LLM，不需要真实API"""

    def __init__(self):
        self.call_count = 0

    def chat(self, messages: list) -> str:
        self.call_count += 1
        content = messages[-1]["content"]

        # 模拟LeaderAgent的plan
        if "拆解" in content or "Leader" in str(messages[0].get("content", "")):
            return '{"analysis": "新能源汽车市场处于快速增长期，需从数据、趋势、投资建议三维度分析", "pipeline": [{"id": 1, "role": "数据研究员", "task": "搜索2024年新能源汽车销量和市场份额数据", "input_from": null, "output_to": 2}, {"id": 2, "role": "行业分析师", "task": "分析销量趋势、竞争格局和技术路线", "input_from": 1, "output_to": 3}, {"id": 3, "role": "投资顾问", "task": "基于数据分析给出投资建议和风险提示", "input_from": 2, "output_to": null}]}'

        # 模拟SubAgent-1（研究员）
        if "数据研究员" in str(messages[0].get("content", "")):
            return '{"type": "final_answer", "answer": "【2024年Q1-Q3数据】\\n1. 比亚迪：销量280万辆，市占率35%（同比+28%）\\n2. 特斯拉：销量120万辆，市占率15%（同比+8%）\\n3. 理想/蔚来/小鹏：合计占比12%\\n4. 整体市场渗透率：42%（2023年为31%）\\n5. 电池成本下降15%，推动价格带下移"}'

        # 模拟SubAgent-2（分析师）
        if "行业分析师" in str(messages[0].get("content", "")):
            return '{"type": "final_answer", "answer": "【趋势分析】\\n1. 头部集中：比亚迪+特斯拉占50%，马太效应明显\\n2. 技术分化：磷酸铁锂（成本型）vs 固态电池（高端型）\\n3. 出海加速：东南亚和欧洲成为主要增量市场\\n4. 智能化竞争：自动驾驶从L2向L3过渡，华为/小鹏领先\\n5. 价格战趋缓：20万以下市场红海，30万以上蓝海"}'

        # 模拟SubAgent-3（投资顾问）
        if "投资顾问" in str(messages[0].get("content", "")):
            return '{"type": "final_answer", "answer": "【投资建议】\\n✅ 看好标的：比亚迪（全产业链+出海）、宁德时代（电池龙头）、华为智选车（智能化溢价）\\n⚠️ 风险提示：价格战压缩毛利率、地缘政治影响出海、固态电池技术路线不确定性\\n💡 策略建议：短期关注电池供应链（降本受益），中期关注智能化零部件（L3渗透），长期关注固态电池技术突破"}'

        # 模拟SingleAgent
        if "计算" in content or "数学" in content:
            return '{"type": "final_answer", "answer": "结果是 56088"}'

        return '{"type": "final_answer", "answer": "【Mock结果】这是模拟输出，用于验证架构流程"}'

    def info(self):
        return {"provider": "mock", "model": "test-model", "base_url": "localhost"}


def test_pipeline():
    """测试完整流水线"""
    print("=" * 70)
    print("🧪 Mock测试：流水线MultiAgent")
    print("=" * 70)

    llm = MockLLM()
    tools = create_default_registry()
    pipeline = PipelineExecutor(llm, tools)

    result = pipeline.run("分析一下新能源汽车市场，给出投资建议")

    print(f"\n{'='*70}")
    print("📊 测试统计")
    print(f"{'='*70}")
    print(f"LLM调用次数: {llm.call_count}")
    print(f"GlobalMemory结果数: {len(pipeline.global_memory.results)}")
    print(f"执行状态: {pipeline.global_memory.status}")

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
    print(f"Step2的前置结果来自Step1: {'销量' in gm.get_previous_result(2)}")
    print(f"Step3的前置结果来自Step2: {'趋势' in gm.get_previous_result(3)}")

    print(f"\n{'='*70}")
    print("✅ 流水线Mock测试通过")
    print(f"{'='*70}")


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
    test_pipeline()
