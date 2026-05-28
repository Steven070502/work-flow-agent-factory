"""
LLM 统一封装层
支持：通义千问 / OpenAI / Kimi / 任何兼容OpenAI接口的模型
切换方式：修改 .env 中的 MODEL_PROVIDER
"""

import os
from typing import Iterator


class LLM:
    """
    统一大语言模型接口
    
    使用方式:
        llm = LLM()  # 自动从.env读取配置
        response = llm.chat([{"role": "user", "content": "你好"}])
    """

    # 预置配置模板，用户只需改.env里的MODEL_PROVIDER
    PROVIDERS = {
        "qwen": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-turbo",
        },
        "qwen-max": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-max",
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
        },
        "dpflash": {
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
        },
        "deeppro": {
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-pro",
        },
        "kimi": {
            "base_url": "https://api.moonshot.cn/v1",
            "model": "moonshot-v1-8k",
        },
    }

    MODEL_ALIASES = {
        "deepseek-flash": "deepseek-v4-flash",
        "deepseek-v4": "deepseek-v4-flash",
        "dpflash": "deepseek-v4-flash",
        "deepseek-pro": "deepseek-v4-pro",
        "dppro": "deepseek-v4-pro",
    }

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = None,
        provider: str = None,
    ):
        """
        初始化LLM
        
        优先级: 传入参数 > 环境变量 > 预置配置
        """
        def clean(value: str | None) -> str | None:
            """读取.env时兼容引号和首尾空白。"""
            if value is None:
                return None
            return value.strip().strip('"').strip("'")

        # 1. 确定 provider
        self.provider = (clean(provider) or clean(os.environ.get("MODEL_PROVIDER")) or "qwen").lower()
        preset = self.PROVIDERS.get(self.provider, self.PROVIDERS["qwen"])

        # 2. 确定最终配置
        self.api_key = clean(api_key) or clean(os.environ.get("API_KEY"))
        self.base_url = clean(base_url) or clean(os.environ.get("BASE_URL")) or preset["base_url"]
        self.model = clean(model) or clean(os.environ.get("MODEL")) or preset["model"]
        self.model = self.MODEL_ALIASES.get(self.model.lower(), self.model)

        if not self.api_key:
            raise ValueError(
                "API_KEY 未设置。请:\n"
                "1. 创建 .env 文件，写入 API_KEY=your_key\n"
                "2. 或在初始化时传入 api_key=\"...\""
            )

        # 3. 创建客户端
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def chat(self, messages: list[dict], stream: bool = False) -> str:
        """
        同步聊天
        
        Args:
            messages: OpenAI格式的消息列表
            stream: 是否流式输出（默认否）
        
        Returns:
            模型生成的文本
        """
        if stream:
            return self._chat_stream(messages)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
        )
        return response.choices[0].message.content

    def _chat_stream(self, messages: list[dict]) -> str:
        """流式聊天，返回完整字符串"""
        chunks = []
        for chunk in self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            stream=True,
        ):
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        return "".join(chunks)

    def info(self) -> dict:
        """返回当前配置信息"""
        protocol = "openai-compatible"
        display_provider = self.provider
        if self.base_url:
            host = self.base_url.lower()
            if self.provider == "dpflash":
                display_provider = "dpflash"
            elif self.provider == "deeppro":
                display_provider = "deeppro"
            elif "dashscope" in host or "aliyuncs" in host:
                display_provider = "qwen"
            elif "deepseek" in host:
                display_provider = "deepseek"
            elif "moonshot" in host:
                display_provider = "kimi"
            elif "openai.com" in host:
                display_provider = "openai"
        return {
            "provider": display_provider,
            "configured_provider": self.provider,
            "protocol": protocol,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": self.api_key[:8] + "..." if self.api_key else None,
        }
