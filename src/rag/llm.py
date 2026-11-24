from groq import Groq
from langchain_aws import ChatBedrockConverse
from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

CONTEXTO_MINIMO_GROQ = 32768


def obter_llm(config: dict) -> BaseChatModel:
    provedor = config["provedor"]
    geracao = config["geracao"]
    if provedor == "bedrock":
        return ChatBedrockConverse(
            model=config["modelos"]["bedrock"],
            region_name=config["modelos"]["regiao"],
            temperature=geracao["temperatura"],
            max_tokens=geracao["max_tokens"],
        )
    if provedor == "groq":
        return ChatGroq(
            model=config["modelos"]["groq"],
            temperature=geracao["temperatura"],
            max_tokens=geracao["max_tokens"],
            reasoning_effort=geracao["raciocinio_groq"] or None,
            max_retries=6,
        )
    raise ValueError(f"provedor desconhecido: {provedor}")


def listar_modelos_groq() -> list[str]:
    """Modelos de chat disponiveis na conta; lista vazia se a chave faltar ou a API falhar."""
    try:
        modelos = Groq().models.list().data
    except Exception:
        return []
    return sorted(modelo.id for modelo in modelos if modelo.context_window >= CONTEXTO_MINIMO_GROQ)
