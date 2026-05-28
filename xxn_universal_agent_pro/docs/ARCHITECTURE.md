# Architecture

XXN Universal Agent is a lightweight **LLM amplifier runtime**.

## Core flow

```text
User
  ↓
InputGuard
  ↓
SingleAgent or PipelineExecutor
  ↓
LeaderAgent plans the pipeline
  ↓
SubAgents execute steps in order
  ↓
GlobalMemory passes outputs downstream
  ↓
FinalSynthesisAgent writes the final answer
  ↓
VerifierAgent checks plan / step / final outputs when enabled
```

## Main modules

- `src/xxn_universal_agent/agents/agent.py` — Agent, Planner, Pipeline, Verifier, Final Synthesis.
- `src/xxn_universal_agent/core/memory.py` — conversation and global pipeline memory.
- `src/xxn_universal_agent/core/llm.py` — provider-agnostic OpenAI-compatible LLM wrapper.
- `src/xxn_universal_agent/core/state.py` — explicit agent state machine.
- `src/xxn_universal_agent/tools/tools.py` — tool registry and default tools.

## Design goal

The framework does not try to replace strong models. It tries to make any model more usable by adding:

- task routing
- stepwise planning
- structured execution
- shared memory
- verifier loops
- final synthesis
