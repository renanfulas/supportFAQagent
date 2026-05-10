from app.llm.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    def generate_answer(self, prompt: str) -> str:
        return (
            "Resposta preliminar gerada pelo mock provider. "
            "Substitua este provider por OpenAI, Anthropic ou outro modelo."
        )
