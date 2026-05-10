import os
from langchain_openai import OpenAIEmbeddings
from langchain_community.embeddings import HuggingFaceEmbeddings

def get_embeddings(provider="openai", model="text-embedding-3-small"):
    if provider == "openai":
        return OpenAIEmbeddings(
            api_key=os.environ.get("OPENAI_API_KEY"),
            model=model
        )
    elif provider == "huggingface":
        # Fallback open source como descrito no documento
        return HuggingFaceEmbeddings(model_name=model)
    else:
        raise ValueError(f"Provider de embedding {provider} não suportado")
