from app.core.config import get_settings
from app.core.errors import ProviderError
from app.llm.base import BaseLLMProvider


class LLMWrapper(BaseLLMProvider):
    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ) -> None:
        self.provider = provider
        settings = get_settings()

        if provider == "openai":
            openai_api_key = api_key or settings.openai_api_key
            if not openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is required for OpenAI provider")
            from langchain_openai import ChatOpenAI

            self.client = ChatOpenAI(
                api_key=openai_api_key,
                model=model,
                temperature=0.0,
            )
        elif provider == "anthropic":
            anthropic_api_key = api_key or settings.anthropic_api_key
            if not anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic provider")
            from langchain_anthropic import ChatAnthropic

            self.client = ChatAnthropic(
                api_key=anthropic_api_key,
                model=model,
                temperature=0.0,
            )
        else:
            raise ValueError(f"Provider {provider} is not supported")

    def generate_answer(self, prompt: str) -> str:
        try:
            response = self.client.invoke(prompt)
            content = str(response.content)
        except Exception as exc:
            raise ProviderError("provider request failed") from exc

        if not content.strip():
            raise ProviderError("provider returned empty response")

        return content

    async def complete(self, prompt: str) -> str:
        try:
            response = await self.client.ainvoke(prompt)
            content = str(response.content)
        except Exception as exc:
            raise ProviderError("provider request failed") from exc

        if not content.strip():
            raise ProviderError("provider returned empty response")

        return content
