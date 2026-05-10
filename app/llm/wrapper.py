import os
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

class LLMWrapper:
    def __init__(self, provider="openai", model="gpt-4o-mini"):
        self.provider = provider
        if provider == 'openai':
            self.client = ChatOpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                model=model,
                temperature=0.0
            )
        elif provider == 'anthropic':
            self.client = ChatAnthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
                model=model,
                temperature=0.0
            )
        else:
            raise ValueError(f"Provider {provider} não suportado")

    async def complete(self, prompt: str) -> str:
        # Retorna apenas o conteúdo da resposta do LLM
        response = await self.client.ainvoke(prompt)
        return response.content
