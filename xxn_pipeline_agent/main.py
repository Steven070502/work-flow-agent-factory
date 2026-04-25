"""
流水线多 Agent 系统 - 主入口

架构：
  InputGuard
      ↓
  LEVEL1: 直接回复（闲聊）
  LEVEL2: 单 Agent（简单问题）
  LEVEL3: Pipeline（复杂任务）
              ↓
         PipelineLeader（规划流水线）
              ↓
         Agent1 → Agent2 → Agent3 → ...
         （每步拿到 Lead 任务 + 前一步输出 + 全局共享记忆）

共享记忆（SharedMemory）贯穿整个进程：
  - 对话历史：跨轮持久，所有 Agent 可读
  - 流水线日志：历史执行记录，Lead 参考，避免重复
  - 当前流水线步骤记录：轮内实时共享，Agent 知道前面发生了什么
"""

import os
import sys
from dotenv import load_dotenv

# 支持直接运行（不需要修改 PYTHONPATH）
sys.path.insert(0, os.path.dirname(__file__))

from llm         import LLM
from input_guard import InputGuard
from shared_memory import SharedMemory
from pipeline    import Pipeline
from memory      import Memory
from agent_simple import SimpleAgent

load_dotenv()

# ── 初始化 LLM ────────────────────────────────────────────────────
llm = LLM(
    api_key  = os.environ.get("DASHSCOPE_API_KEY"),
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model    = "qwen-turbo",
)

# ── 全局单例：贯穿整个进程的共享记忆 ─────────────────────────────
shared_memory = SharedMemory(
    system_context=(
        "你是一个多Agent协作系统，专门处理复杂任务。"
        "系统由一个 Lead Agent 和若干流水线子 Agent 组成，"
        "子 Agent 顺序执行，共享全局记忆，结果逐步传递。"
    )
)

# ── 其他组件 ──────────────────────────────────────────────────────
input_guard = InputGuard(llm)
pipeline    = Pipeline(llm)

# ── 启动界面 ──────────────────────────────────────────────────────
print("=" * 65)
print("  流水线多 Agent 系统")
print("  输入 q 退出  |  输入 mem 查看共享记忆状态")
print("=" * 65)

while True:
    print()
    issue = input("请输入你的问题：").strip()

    if not issue:
        continue

    if issue.lower() in ("q", "quit", "退出"):
        print("再见！")
        break

    if issue.lower() == "mem":
        shared_memory.debug_dump()
        continue

    # ── 拼接历史上下文（让 InputGuard 也能感知历史）──────────────
    conv_summary = shared_memory.get_conversation_summary(max_chars=1000)
    if conv_summary != "（无历史对话）":
        full_input = f"【历史对话摘要】\n{conv_summary}\n\n【当前问题】{issue}"
    else:
        full_input = issue

    # ── InputGuard 判断 ───────────────────────────────────────────
    check = input_guard.check(full_input)

    if not check["pass"]:
        # LEVEL1：闲聊，直接回复
        reply = check["direct_response"]
        print(f"\n{reply}")
        shared_memory.add_conversation("user",      issue)
        shared_memory.add_conversation("assistant", reply)
        continue

    elif check["level"] == "simple":
        # LEVEL2：简单问题，单 Agent
        worker = SimpleAgent(llm)
        result = worker.run(full_input)
        print(f"\n{result}")
        shared_memory.add_conversation("user",      issue)
        shared_memory.add_conversation("assistant", result)

    else:
        # LEVEL3：复杂问题，流水线
        result = pipeline.run(full_input, shared_memory)
        shared_memory.add_conversation("user",      issue)
        shared_memory.add_conversation("assistant", result)
