class Memory:
    def __init__(self,system_prompt:str):
        self.messages = [
            {"role" : "system" , "content" : system_prompt}
        ]

    def add(self, role: str, content: str):
        """塞到messages后面"""
        self.messages.append({"role": role, "content": content})

    def get(self) -> list[dict]:
        """返回完整历史，直接传给 LLM"""
        return self.messages

    def clear(self):
        """只保留 system prompt，清空其余历史"""
        self.messages = self.messages[:1]    