import argparse
import sys
from collections.abc import Callable

from langchain_aws import BedrockEmbeddings, BedrockRerank, ChatBedrockConverse
from langchain_core.documents import Document as DocumentoLangchain
from langchain_groq import ChatGroq

from src.configuracao import carregar_config
from src.ingestao.construir_indice import carregar_embedder_local, eh_hugging_face
from src.rag.recuperador import carregar_reordenador_local

DIAGNOSTICOS = [
    ("on-demand throughput", "sem acesso direto: use o id do inference profile (us. ou global.)"),
    ("Could not resolve the foundation model", "id inválido ou modelo indisponível nesta região"),
    ("model identifier is invalid", "id inválido ou modelo indisponível nesta região"),
    ("ThrottlingException", "acesso existe, mas a cota foi atingida agora"),
    ("Too many requests", "acesso existe, mas a cota foi atingida agora"),
    ("ExpiredToken", "credencial AWS expirada"),
    ("UnrecognizedClient", "credencial AWS inválida"),
    ("InvalidSignature", "credencial AWS inválida"),
    ("Unable to locate credentials", "credencial AWS não encontrada no .env"),
    ("AccessDenied", "sem acesso: modelo não liberado na conta ou usuário sem permissão"),
    ("ResourceNotFound", "modelo não encontrado ou descontinuado para esta conta"),
    ("ValidationException", "chamada recusada: confira o id do modelo"),
    ("GROQ_API_KEY", "chave do Groq não configurada: informe em Configurações"),
    ("Invalid API Key", "chave do Groq inválida"),
    ("model_not_found", "modelo não encontrado no Groq: confira o nome"),
    ("rate_limit_exceeded", "acesso existe, mas o limite do Groq foi atingido agora"),
    ("is not a local folder and is not a valid model identifier", "modelo não encontrado no Hugging Face"),
]


def testar_chat(modelo: str, regiao: str) -> None:
    ChatBedrockConverse(model=modelo, region_name=regiao, max_tokens=5).invoke("Responda ok")


def testar_groq(modelo: str, regiao: str) -> None:
    ChatGroq(model=modelo, max_tokens=5).invoke("Responda ok")


def testar_embedding(modelo: str, regiao: str) -> None:
    if eh_hugging_face(modelo):
        carregar_embedder_local(modelo).embed_query("teste")
        return
    argumentos = {"input_type": "search_query"} if modelo.startswith("cohere.") else None
    BedrockEmbeddings(model_id=modelo, region_name=regiao, model_kwargs=argumentos).embed_query("teste")


def testar_rerank_local(modelo: str, regiao: str) -> None:
    carregar_reordenador_local(modelo).rank("teste", ["teste"])


def testar_rerank(modelo: str, regiao: str) -> None:
    arn = f"arn:aws:bedrock:{regiao}::foundation-model/{modelo}"
    BedrockRerank(model_arn=arn, region_name=regiao).rerank(
        documents=[DocumentoLangchain(page_content="teste")], query="teste", top_n=1
    )


def escolher_teste(modelo: str) -> Callable[[str, str], None]:
    if "rerank" in modelo:
        return testar_rerank
    if "embed" in modelo:
        return testar_embedding
    return testar_chat


TESTES_POR_CHAVE = {"groq": testar_groq, "juiz_groq": testar_groq, "rerank_hf": testar_rerank_local}


def chaves_em_uso(config: dict) -> tuple[str, ...]:
    geracao = ("groq", "juiz_groq") if config["provedor"] == "groq" else ("bedrock", "juiz")
    rerank = "rerank_hf" if eh_hugging_face(config["modelos"]["embedding"]) else "rerank"
    return (*geracao, "embedding", rerank)


def diagnosticar(erro: Exception) -> str:
    mensagem = f"{type(erro).__name__}: {erro}"
    for trecho, explicacao in DIAGNOSTICOS:
        if trecho in mensagem:
            return explicacao
    return "falha não classificada"


def testar(modelo: str, regiao: str) -> bool:
    try:
        escolher_teste(modelo)(modelo, regiao)
    except Exception as erro:
        print(f"[SEM ACESSO] {modelo} ({regiao}): {diagnosticar(erro)}")
        print(f"             {type(erro).__name__}: {str(erro)[:300]}")
        return False
    print(f"[OK] {modelo} ({regiao})")
    return True


def principal() -> None:
    analisador = argparse.ArgumentParser(description="Testa o acesso a modelos do Bedrock")
    analisador.add_argument("modelos", nargs="*", help="ids; sem id, testa os do config.yaml")
    analisador.add_argument("--regiao")
    analisador.add_argument("--config", default="config.yaml")
    argumentos = analisador.parse_args()

    modelos_config = carregar_config(argumentos.config)["modelos"]
    regiao = argumentos.regiao or modelos_config["regiao"]
    modelos = argumentos.modelos or [
        modelos_config[chave] for chave in ("bedrock", "juiz", "embedding", "rerank")
    ]
    resultados = [testar(modelo, regiao) for modelo in modelos]
    sys.exit(0 if all(resultados) else 1)


if __name__ == "__main__":
    principal()
