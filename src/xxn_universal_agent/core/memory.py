"""
记忆系统
支持：短期上下文 + 长期摘要 + 持久化存储
"""

import json
import os
from datetime import datetime
from typing import List, Dict


class Memory:
    """
    对话记忆管理器
    
    职责:
    - 维护对话历史
    - 控制上下文窗口（防止Token爆炸）
    - 支持对话导出/导入
    """

    def __init__(
        self,
        system_prompt: str = "",
        max_messages: int = 20,
        auto_summarize: bool = True,
    ):
        """
        Args:
            system_prompt: 系统提示词
            max_messages: 保留的最大消息数（不含system）
            auto_summarize: 超限时是否自动摘要历史
        """
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self.auto_summarize = auto_summarize
        self.messages: List[Dict[str, str]] = []
        self.summary: str = ""  # 历史摘要

        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

    def add(self, role: str, content: str):
        """添加一条消息"""
        self.messages.append({"role": role, "content": content})
        self._check_overflow()

    def get(self) -> List[Dict[str, str]]:
        """获取完整的对话历史（含system和summary）"""
        result = []

        # system prompt
        if self.messages and self.messages[0]["role"] == "system":
            result.append(self.messages[0])

        # 如果有摘要，插入作为上下文
        if self.summary:
            result.append({
                "role": "system",
                "content": f"【历史摘要】{self.summary}"
            })

        # 最近的消息
        for msg in self.messages[1:]:
            result.append(msg)

        return result

    def get_recent(self, n: int = 5) -> List[Dict[str, str]]:
        """获取最近n条用户和助手消息"""
        recent = []
        for msg in reversed(self.messages):
            if msg["role"] in ("user", "assistant"):
                recent.append(msg)
            if len(recent) >= n:
                break
        return list(reversed(recent))

    def clear(self):
        """清空对话，保留system prompt"""
        if self.messages and self.messages[0]["role"] == "system":
            self.messages = [self.messages[0]]
        else:
            self.messages = []
        self.summary = ""

    def export(self, filepath: str):
        """导出对话到JSON文件"""
        data = {
            "system_prompt": self.system_prompt,
            "summary": self.summary,
            "messages": self.messages,
            "timestamp": datetime.now().isoformat(),
        }
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, filepath: str):
        """从JSON文件导入对话"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.system_prompt = data.get("system_prompt", "")
        self.summary = data.get("summary", "")
        self.messages = data.get("messages", [])

    def _check_overflow(self):
        """检查消息是否溢出，处理策略：摘要+裁剪"""
        # 只统计 user/assistant 消息
        chat_msgs = [m for m in self.messages if m["role"] in ("user", "assistant")]

        if len(chat_msgs) > self.max_messages:
            if self.auto_summarize:
                # 将超过部分标记为待摘要（实际摘要由外部LLM完成）
                overflow = chat_msgs[:-self.max_messages]
                overflow_text = "\n".join(
                    f"{m['role']}: {m['content'][:100]}"
                    for m in overflow
                )
                self.summary += f"[之前对话要点] {overflow_text}\n"

            # 保留 system + 最近消息
            recent = [m for m in self.messages if m["role"] in ("user", "assistant")][-self.max_messages:]
            if self.messages and self.messages[0]["role"] == "system":
                self.messages = [self.messages[0]] + recent
            else:
                self.messages = recent

    def __len__(self) -> int:
        return len(self.messages)
