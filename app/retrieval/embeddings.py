from app.core.config import get_settings
from app.domain_engine.models import DomainConfig


def get_embeddings(provider: str = "openai", model: str = "text-embedding-3-small"):
    provider_name = provider.lower().strip()

    if provider_name == "openai":
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI embeddings")
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model=model,
        )

    if provider_name in {"huggingface", "local"}:
        from langchain_community.embeddings import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name=model)

    raise ValueError(f"Embedding provider {provider} is not supported")


def get_domain_embeddings(domain: DomainConfig):
    return get_embeddings(
        provider=domain.embedding.provider,
        model=domain.embedding.model,
    )
