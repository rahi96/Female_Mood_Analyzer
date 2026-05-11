import anthropic
from ai.config import settings


class ClaudeLLM:
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.CLAUDE_API_KEY
        self.model = model or settings.CLAUDE_MODEL
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def chat(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = None,
        system: str = None,
    ):
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if system:
            kwargs["system"] = system
        return self.client.messages.create(**kwargs)

    def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = None,
        system: str = None,
    ):
        return self.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
        )
