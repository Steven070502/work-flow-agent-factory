# XXN Universal Agent Framework

> 一个轻量级 LLM 能力放大器：通过任务拆解、流水线执行、共享记忆、Verifier 和最终综合，让弱模型更可用，让强模型更稳定。

## Quick Start

```bash
pip install -r requirements.txt
python main.py --test
python tests/test_pipeline.py
```

也可以用脚本：

```bash
bash scripts/run_mock.sh
bash scripts/test.sh
```

## Project Layout

```text
xxn_universal_agent/
├── src/xxn_universal_agent/   # 核心源码
│   ├── agents/                # Agent / Pipeline / Verifier
│   ├── core/                  # LLM / Memory / StateMachine
│   ├── tools/                 # 工具系统
│   └── cli.py                 # CLI 入口
├── tests/                     # 测试
├── scripts/                   # 常用脚本
├── docs/                      # 文档
├── Dockerfile                 # 容器运行
├── pyproject.toml             # Python 包配置
├── requirements.txt           # 依赖
├── .env.example               # 环境变量模板，不含真实 Key
└── main.py                    # 本地启动入口
```

## Docker

```bash
docker build -t xxn-universal-agent .
docker run --rm xxn-universal-agent
```

## Safe GitHub Submission

真实密钥只放本地 `.env`，不要提交。公开仓库只提交 `.env.example`。

---

> 流水线式多Agent协作框架：解决记忆互通与输出质量两大致命痛点。

---

## 一、为什么现有的 Multi-Agent 设计是垃圾

当你说"帮我分析一下新能源汽车市场"，99%的 Multi-Agent 框架会返回这样的东西：

```
Worker-1: 已搜索相关信息
Worker-2: 已整理市场数据
Worker-3: 已分析竞品策略

汇总: 市场竞争激烈，建议关注技术发展和用户需求。
```

**这是垃圾。** 为什么？

| 问题 | 后果 |
|------|------|
| 各 Agent 独立运行，互不感知 | A 干了什么 B 不知道，信息孤岛 |
| 没有数据传递关系 | "已搜索"的结果长什么样？没人知道，也没传给下游 |
| 输出都是状态描述 | "已完成""已整理"——这种输出下游能消费吗？不能 |
| 没有全局上下文 | 第三个 Agent 忘了原始任务是什么，也忘了 Leader 定的方向 |
| 并行跑完自己拼 | 你拿到 4 个独立碎片，还得自己当胶水 |

**传统 Multi-Agent 的特征向量：**

```
协作模式: 并行独立，无数据流
Agent 间通信: ❌ 无
记忆共享: ❌ 各自为政
输出质量: 状态描述（"已完成"）
可用性: 需要人类当胶水拼结果
```

**本框架的特征向量：**

```
协作模式: 串行流水线，上一步输出 = 下一步输入
Agent 间通信: ✅ 通过 GlobalMemory 共享
记忆共享: ✅ 中心化上下文池
输出质量: 具体交付物（数据/分析/结论）
可用性: 自动出报告，无需拼接
```

---

## 二、核心差异

### 2.1 流水线 vs 并行

```
并行 Multi-Agent:
  ┌─→ Agent-A (搜索) ─┐
  ├─→ Agent-B (整理) ─┤ → 你自己拼
  ├─→ Agent-C (分析) ─┤
  └─→ Agent-D (输出) ─┘

流水线 Multi-Agent（本框架）:
  Agent-1 (研究员) → 具体数据
         ↓
  Agent-2 (分析师) → 结构化分析（基于上一步数据）
         ↓
  Agent-3 (撰写员) → 完整报告（基于上一步分析）
```

### 2.2 GlobalMemory：中心化上下文池

传统设计：每个 Agent 有自己的 Memory，互相看不到。

本框架：**所有 Agent 读写同一个 GlobalMemory**。

```python
GlobalMemory:
  - original_task     ← 用户原始需求
  - leader_analysis   ← Leader 的核心分析
  - pipeline          ← 子任务定义
  - results[1]        ← Step 1 的具体交付物
  - results[2]        ← Step 2 的具体交付物
  - agent_histories   ← 每个 Agent 的对话历史
```

### 2.3 强制输出质量

| 输出类型 | 传统框架 | 本框架 |
|---------|---------|--------|
| 研究员 | "已完成数据收集" | "Python 平均年薪 25-40 万，岗位 12 万，热门方向 AI/大模型..." |
| 分析师 | "已整理分析" | "薪资对比：Python 天花板更高... 岗位对比：JS 更多但增长放缓..." |
| 撰写员 | "已生成报告" | "建议选 Python，理由是... 风险提示..." |

**硬性规则**：
- 禁止输出"已完成""无法完成""缺少工具"等状态描述
- 必须输出具体数据、事实、分析、结论
- 输出要像"交接文档"——下一个同事拿到就能继续工作

---

## 三、架构

```
用户输入
    │
    ▼
┌─────────────────┐
│   InputGuard    │
│   ├── LEVEL1    │ → 闲聊问候 → 直接回复
│   ├── LEVEL2    │ → 简单问题 → SingleAgent
│   └── LEVEL3    │ → 复杂任务 → Pipeline MultiAgent
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│      LeaderAgent            │
│  - 分析任务核心              │
│  - 拆解为串行流水线           │
│  - 为每步分配角色            │
│  - 定义 input_from/output_to │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│         Pipeline Executor                    │
│                                              │
│  Step 1 [研究员]                             │
│    输入: 原始任务 + Leader分析 + 全局上下文    │
│    输出: 具体数据/事实（交付物）              │
│         ↓ 写入 GlobalMemory.results[1]       │
│                                              │
│  Step 2 [分析师]                             │
│    输入: results[1] + 全局上下文              │
│    输出: 结构化分析/对比/洞察（交付物）       │
│         ↓ 写入 GlobalMemory.results[2]       │
│                                              │
│  Step 3 [撰写员]                             │
│    输入: results[2] + 全局上下文              │
│    输出: 完整报告/建议/结论（交付物）         │
│         ↓                                    │
│    最终汇总报告                                │
└─────────────────────────────────────────────┘
```

---

## 四、模块职责

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| **InputGuard** | 输入分级 | 用户自然语言 | `{"pass": true/false, "level": "simple"/"complex"}` |
| **LeaderAgent** | 战略拆解 | 原始任务 | 流水线计划（含角色、依赖、顺序） |
| **SubAgent** | 战术执行 | 角色 + 任务 + 前置结果 + 全局上下文 | 具体交付物（数据/分析/结论） |
| **PipelineExecutor** | 执行调度 | 原始任务 | 串行执行 + 结果汇总 |
| **GlobalMemory** | 上下文共享 | 所有 Agent 的写入 | 全局状态、历史结果、对话记录 |
| **SingleAgent** | 简单任务 | 用户问题 | 直接答案 |

---

## 五、快速开始

### 5.1 安装

```bash
cd xxn_universal_agent
pip install -r requirements.txt
```

### 5.2 配置

```bash
# 真实 API 模式
cp .env.example .env
# 然后打开 .env，把 API_KEY 改成你自己的真实 Key

# Mock 测试模式（无需 Key）
# 直接加 --test 参数运行
```

### 5.3 运行

```bash
# 真实 API
python main.py

# Mock 测试（无需 Key）
python main.py --test
```

---

## 六、使用示例

### 6.1 Mock 测试（无需 API Key）

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
**原始需求**: ...
**Leader分析**: ...
---
## Step 1: [数据研究员] ...
...
## Step 2: [对比分析师] ...
...
## Step 3: [职业顾问] ...
...
```

### 6.2 多轮对话（跨轮次记忆）

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

## 七、核心设计原理

### 7.1 为什么串行不是并行？

并行的问题是：你拿到 4 个独立结果，还要自己当胶水拼。

流水线：**上一步的输出 = 下一步的输入**。数据自然流动，不需要事后拼接。

### 7.2 为什么需要 GlobalMemory？

传统 Multi-Agent：每个 Agent 有自己的 Memory，A 不知道 B 做了什么，C 忘了原始任务是什么。

GlobalMemory：**中心化上下文池**。原始任务、Leader 分析、每步结果，全部集中存储。每个 Agent 读取同一个数据源。

### 7.3 为什么强制输出质量？

真实 LLM 有个毛病：搜索不到数据就说"无法完成"，或者一句"已完成"就交差。

本框架通过 Prompt 硬约束：
- **红线**：禁止输出"已完成""无法完成""缺少工具"
- **标准**：必须输出具体数据/事实/分析/结论
- **定位**：你的输出是"交接文档"

---

## 八、项目结构

```
xxn_universal_agent/
│
├─ main.py                    ← 入口
│   ├─ InputGuard（输入分级）
│   ├─ 全局对话历史（跨轮次记忆）
│   └─ SingleAgent / Pipeline 路由
│
├─ core/                      ← 基础设施
│   ├─ llm.py                 ← LLM封装（多模型切换）
│   ├─ memory.py              ← 记忆系统（上下文+摘要）
│   └─ state.py               ← 状态机
│
├─ agents/
│   └─ agent.py               ← 🔥 核心
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

## 九、配置

编辑 `.env`：

```env
# 必填
API_KEY=sk-your-api-key-here

# 选填（默认通义千问）
MODEL_PROVIDER=qwen        # qwen / qwen-max / openai / kimi
```

| 提供商 | MODEL_PROVIDER | 默认模型 |
|--------|---------------|---------|
| 通义千问 | `qwen` | qwen-turbo |
| 通义千问(强) | `qwen-max` | qwen-max |
| OpenAI | `openai` | gpt-4o-mini |
| Kimi | `kimi` | moonshot-v1-8k |

自定义接口：
```env
MODEL_PROVIDER=openai
API_KEY=sk-xxx
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o
```

---

## 十、扩展

### 10.1 添加工具

在 `tools/tools.py` 中：

```python
class MyTool(Tool):
    name = "my_tool"
    description = "工具描述"
    
    def run(self, input: str) -> str:
        return "结果"
```

然后在 `create_default_registry()` 中注册。

### 10.2 调整流水线深度

修改 `LeaderAgent.SYSTEM_PROMPT`：
```
拆解为2-5个串行子任务   # 改为 3-7 个
```

### 10.3 修改输出质量标准

修改 `SubAgent.run()` 中的 `system_prompt`，调整【核心红线】和【输出质量标准】。

---

## 十一、常见问题

**Q: 为什么 Agent 说"无法完成，缺少工具"？**

A: 真实 LLM 比较谨慎。本框架已通过 Prompt 强制要求：即使工具不可用，也必须基于知识给出详细回答。

**Q: Mock 测试通过，真实 API 失败？**

A: 检查 `.env` 中的 `API_KEY` 是否有效。

**Q: 怎么让 Agent 记住之前的对话？**

A: 框架已内置跨轮次记忆，无需额外配置。

**Q: 输出太短/太简单怎么办？**

A: 在 `SubAgent` 的 System Prompt 中调整【输出质量标准】。

---

MIT License
