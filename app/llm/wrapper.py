from app.core.config import get_settings
from app.llm.base import BaseLLMProvider


class LLMWrapper(BaseLLMProvider):
    def __init__(self, provider: str = "openai", model: str = "gpt-4o-mini") -> None:
        self.provider = provider
        settings = get_settings()

        if provider == "openai":
            if not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is required for OpenAI provider")
            from langchain_openai import ChatOpenAI

            self.client = ChatOpenAI(
                api_key=settings.openai_api_key,
                model=model,
                temperature=0.0,
            )
        elif provider == "anthropic":
            if not settings.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic provider")
            from langchain_anthropic import ChatAnthropic

            self.client = ChatAnthropic(
                api_key=settings.anthropic_api_key,
                model=model,
                temperature=0.0,
            )
        else:
            raise ValueError(f"Provider {provider} is not supported")

    def generate_answer(self, prompt: str) -> str:
        response = self.client.invoke(prompt)
        return str(response.content)

    async def complete(self, prompt: str) -> str:
        response = await self.client.ainvoke(prompt)
        return str(response.content)
