# XXN Universal Agent Framework

> 流水线式多Agent框架：解决记忆互通痛点，强制输出质量，支持串行任务传递。

---

## 一句话定位

输入一个复杂任务 → **Leader拆解流水线** → **Agent串行执行** → **每步输出具体交付物** → **最终报告**。

不是并行各干各的，是**流水线接力**：上一步的输出 = 下一步的输入。

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **流水线（Pipeline）** | Leader把任务拆成串行步骤，数据在Agent之间传递，不是并行各干各的 |
| **全局记忆（GlobalMemory）** | 所有Agent共享同一个上下文池，原始任务、Leader分析、每步结果都集中存储 |
| **强制输出质量** | 每个Agent必须输出具体数据/分析/结论，禁止"已完成""无法完成"等状态描述 |
| **InputGuard** | 自动判断输入级别：闲聊直接回 / 简单问题单Agent / 复杂任务走流水线 |
| **跨轮次记忆** | 多轮对话中，Agent能记住之前说过什么（"重复上一个回答"能正常工作） |
| **多模型切换** | 通义千问 / OpenAI / Kimi，改一行配置即可切换 |

---

## 架构

```
用户输入
    │
    ▼
┌─────────────────┐
│   InputGuard    │ ← 判断：闲聊？简单？复杂？
│   ├── LEVEL1    │    → 直接回复
│   ├── LEVEL2    │    → SingleAgent（单Agent ReAct循环）
│   └── LEVEL3    │    → Pipeline MultiAgent（走下方完整流程）
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│      LeaderAgent（领导）      │
│  分析整体任务 → 拆解流水线     │
│  为每步分配角色 + 定义依赖     │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│         Pipeline Executor                    │
│                                              │
│  Step 1 [研究员]                             │
│    输入: 原始任务 + Leader分析 + 全局上下文    │
│    输出: 具体数据/事实（交付物）              │
│         ↓ 结果存入 GlobalMemory              │
│                                              │
│  Step 2 [分析师]                             │
│    输入: Step1交付物 + 全局上下文             │
│    输出: 结构化分析/对比/洞察（交付物）       │
│         ↓ 结果存入 GlobalMemory              │
│                                              │
│  Step 3 [撰写员]                             │
│    输入: Step2交付物 + 全局上下文             │
│    输出: 完整报告/建议/结论（交付物）         │
│         ↓                                    │
│    最终汇总报告                                │
└─────────────────────────────────────────────┘
```

---

## 快速开始

### 1. 安装依赖

```bash
cd xxn_universal_agent
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# 方式1：真实API（推荐）
echo "API_KEY=sk-你的真实Key" > .env

# 方式2：Mock模式（无Key测试框架流程）
# 什么都不用配，直接加 --test 参数运行
```

### 3. 运行

```bash
# 真实API模式
python main.py

# Mock测试模式（无需Key，模拟完整流水线）
python main.py --test
```

---

## 使用示例

### Mock 测试（无需 API Key）

```bash
python main.py --test
```

```
You > 分析Python和JavaScript在2024年的就业趋势，
      对比两者的薪资水平、岗位数量、热门技术方向，
      最后给出一个2025年初学者的语言选择建议

[模式: Pipeline MultiAgent 复杂任务]

============================================================
🎯 原始任务: 分析Python和JavaScript在2024年的就业趋势...
============================================================

[Step 0] Leader分析并拆解任务...
  📋 核心分析: Python在AI/数据领域强势，JS在Web前端主导...
  📊 拆解为 3 个串行任务:
     Step 1: [数据研究员] 搜索2024年就业薪资... (起点) →
     Step 2: [对比分析师] 基于数据对比差异... (接Step1) →
     Step 3: [职业顾问] 给出初学者建议... (接Step2) →[终]

============================================================
开始流水线执行...
============================================================

--- Step 1/3 ---
🎭 角色: 数据研究员
📝 任务: 搜索2024年就业薪资、岗位数量、热门方向数据
📥 前置输入: (无，你是第一个)
📤 输出结果: 【2024年就业数据】
  Python: 平均年薪25-40万，岗位12万，热门方向AI/大模型...
  JavaScript: 平均年薪18-35万，岗位15万，热门方向React/Vue...

--- Step 2/3 ---
🎭 角色: 对比分析师
📝 任务: 基于数据对比两者薪资、岗位、技术方向的差异和趋势
📥 前置输入: 【2024年就业数据】Python: 平均年薪25-40万...
📤 输出结果: 【对比分析】
  1. 薪资对比: Python天花板更高...
  2. 岗位数量: JS更多但Python增长更快...
  3. 技术方向: Python AI壁垒强，JS生态广但内卷...

--- Step 3/3 ---
🎭 角色: 职业顾问
📝 任务: 基于对比分析，结合初学者身份给出建议
📥 前置输入: 【对比分析】1. 薪资对比: Python天花板更高...
📤 输出结果: 【2025初学者选择建议】
  选Python如果你: 目标AI/数据，能承受6个月学习曲线...
  选JS如果你: 想快速出成果，目标全栈/前端...
  我的建议: 优先Python，AI时代基础设施...

============================================================
流水线执行完毕，生成最终报告...
============================================================

# 任务完成报告
...
```

### 真实 API 运行

```bash
# 填入你的Key
echo "API_KEY=sk-xxxxx" > .env

# 运行
python main.py
```

```
You > 帮我写一个能备份文件夹的Python脚本

[模式: SingleAgent 简单处理]

📋 结果:
import shutil
import os
from datetime import datetime

def backup_folder(src, dst):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(dst, f"backup_{timestamp}")
    shutil.copytree(src, backup_path)
    return backup_path

...
```

### 多轮对话（跨轮次记忆）

```
You > 分析Python和JavaScript就业趋势...
Agent > [长篇报告]

You > 刚才说的薪资数据再详细点
Agent > [基于上一轮，补充薪资细节]

You > 那如果我是初学者呢
Agent > [基于前两轮，给出针对初学者的建议]

You > 重复第一个问题的完整回答
Agent > [复述完整的就业趋势报告]
```

---

## 核心设计原理

### 为什么用串行而不是并行？

并行MultiAgent的问题是：每个Agent独立运行，互不感知。你拿到4个子结果，还要自己拼。

流水线的优势是：**上一步的输出 = 下一步的输入**。数据自然流动，不需要事后拼接。

```
并行:  A独立跑 → B独立跑 → C独立跑 → 你自己拼结果
流水线: A跑完 → 结果传给B → B跑完 → 结果传给C → 自动出报告
```

### 为什么需要 GlobalMemory？

传统MultiAgent每个Agent有自己的Memory，导致：
- Agent A不知道Agent B做了什么
- Agent C不知道原始任务是什么
- 结果无法追溯

GlobalMemory是一个**中心化上下文池**：
- 原始任务、Leader分析、每步结果，全部集中存储
- 每个Agent读取同一个数据源
- 彻底消除信息孤岛

### 为什么强制输出质量？

真实LLM有个毛病：搜索不到数据就说"无法完成"，或者一句"已完成"就交差。

本框架通过Prompt硬约束解决：
- **红线**：禁止输出"已完成""无法完成""缺少工具"
- **标准**：必须输出具体数据/事实/分析/结论
- **定位**：你的输出是"交接文档"，下一个同事拿到就能继续

---

## 项目结构

```
xxn_universal_agent/
│
├─ main.py                    ← 入口
│   ├─ InputGuard（输入分级）
│   ├─ 全局对话历史（跨轮次记忆）
│   └─ SingleAgent / Pipeline 路由
│
├─ core/                      ← 基础设施
│   ├─ llm.py                 ← LLM封装（通义千问/OpenAI/Kimi）
│   ├─ memory.py              ← 记忆系统（上下文窗口+摘要）
│   └─ state.py               ← 状态机（IDLE→THINKING→ACTING→...）
│
├─ agents/
│   └─ agent.py               ← 🔥 核心逻辑
│       ├─ GlobalMemory       ← 全局共享记忆池
│       ├─ LeaderAgent        ← 拆解流水线、定角色、定依赖
│       ├─ SubAgent           ← 执行节点（强制输出质量）
│       ├─ PipelineExecutor   ← 串行执行器
│       └─ SingleAgent        ← 单Agent（简单任务）
│
├─ tools/
│   └─ tools.py               ← 工具注册表
│       ├─ calculate          ← 数学计算
│       ├─ execute_python     ← Python代码执行（沙箱）
│       ├─ search             ← 网络搜索（DuckDuckGo）
│       ├─ read_file          ← 读取文件
│       ├─ write_file         ← 写入文件
│       └─ think              ← 思考记录
│
├─ .env.example               ← 配置模板
├─ requirements.txt           ← 依赖
├─ test_pipeline.py           ← Mock测试脚本
└─ README.md                  ← 本文档
```

---

## 配置说明

编辑 `.env` 文件：

```env
# 必填
API_KEY=sk-your-api-key-here

# 选填（默认通义千问）
MODEL_PROVIDER=qwen        # qwen / qwen-max / openai / kimi
```

| 提供商 | MODEL_PROVIDER | 默认模型 | 接口地址 |
|--------|---------------|---------|---------|
| 通义千问 | `qwen` | qwen-turbo | 阿里云 |
| 通义千问(强) | `qwen-max` | qwen-max | 阿里云 |
| OpenAI | `openai` | gpt-4o-mini | OpenAI |
| Kimi | `kimi` | moonshot-v1-8k | Moonshot |

也可以直接指定自定义接口：
```env
MODEL_PROVIDER=openai
API_KEY=sk-xxx
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o
```

---

## 扩展指南

### 添加新工具

在 `tools/tools.py` 中：

```python
class MyTool(Tool):
    name = "my_tool"
    description = "工具描述"
    
    def run(self, input: str) -> str:
        return "结果"
```

然后在 `create_default_registry()` 中注册。

### 调整流水线深度

修改 `LeaderAgent.SYSTEM_PROMPT` 中的约束：
```
拆解为2-5个串行子任务   # 改为 3-7 个
```

### 修改输出质量标准

修改 `SubAgent.run()` 中的 `system_prompt`，调整【核心红线】和【输出质量标准】部分。

---

## 常见问题

**Q: 为什么 Agent 说"无法完成，缺少工具"？**
A: 真实LLM比较谨慎。本框架已通过Prompt强制要求：即使工具不可用，也必须基于知识给出详细回答。如果还出现，检查 `agents/agent.py` 中 SubAgent 的 System Prompt 是否正确加载。

**Q: Mock 测试通过，真实 API 失败？**
A: 检查 `.env` 中的 `API_KEY` 是否有效。Mock模式不需要Key，真实模式需要。

**Q: 怎么让 Agent 记住之前的对话？**
A: 框架已内置跨轮次记忆（`conversation_history`），无需额外配置。直接多轮对话即可。

**Q: 输出太短/太简单怎么办？**
A: 在 `SubAgent` 的 System Prompt 中调整【输出质量标准】，明确要求输出长度和深度。

---

## 许可证

MIT
