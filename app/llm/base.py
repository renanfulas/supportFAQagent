from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate_answer(self, prompt: str) -> str:
        raise NotImplementedError
