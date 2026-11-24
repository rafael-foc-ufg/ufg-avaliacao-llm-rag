import argparse
import time
from collections.abc import Callable
from functools import cache
from itertools import batched, islice
from pathlib import Path

from botocore.config import Config
from langchain_aws import BedrockEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document as DocumentoLangchain
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.configuracao import carregar_config
from src.ingestao import cjf, legislacao
from src.ingestao.modelo import Documento

COLECOES = {"cjf": "jurisprudencia", "legislacao": "legislacao"}
LOTE_EMBEDDING = 96
TENTATIVAS_EMBEDDING = 15
CARACTERES_POR_SEGUNDO_EMBEDDING = 15000

SEPARADORES_PADRAO = ["\n\n", "\n", ". ", " ", ""]
SEPARADORES_LEGISLACAO = ["\nArt. ", "\n\n", "\n", ". ", " ", ""]


def ler_documentos(config: dict, fonte: str) -> dict[str, Documento]:
    """O mesmo processo pode vir repetido nos CSVs; vale a ultima ocorrencia."""
    caminhos = config["caminhos"]
    documentos = (
        cjf.ler_diretorio(Path(caminhos["base_cjf"]))
        if fonte == "cjf"
        else legislacao.ler_diretorio(Path(caminhos["base_juridica"]))
    )
    return {documento.doc_id: documento for documento in documentos}


def criar_divisor(fonte: str, config: dict) -> RecursiveCharacterTextSplitter:
    separadores = SEPARADORES_LEGISLACAO if fonte == "legislacao" else SEPARADORES_PADRAO
    return RecursiveCharacterTextSplitter(
        chunk_size=config["chunking"]["tamanho"],
        chunk_overlap=config["chunking"]["overlap"],
        separators=separadores,
        keep_separator=True,
    )


def chunks_de(
    documento: Documento, divisor: RecursiveCharacterTextSplitter
) -> list[DocumentoLangchain]:
    metadados = {
        "doc_id": documento.doc_id,
        "fonte": documento.fonte,
        "titulo": documento.titulo,
    }
    for chave, valor in documento.meta.items():
        metadados[chave] = valor if isinstance(valor, (str, int, float, bool)) else str(valor)
    return divisor.create_documents([documento.texto], metadatas=[metadados])


def eh_hugging_face(modelo: str) -> bool:
    """Ids do Hugging Face tem o formato organizacao/modelo; os do Bedrock nao tem barra."""
    return "/" in modelo


@cache
def carregar_embedder_local(modelo: str) -> Embeddings:
    """Importa aqui porque o torch atrasa em segundos qualquer comando que nao use Hugging Face."""
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=modelo, encode_kwargs={"normalize_embeddings": True})


def obter_embedder(config: dict, tipo_entrada: str) -> Embeddings:
    if eh_hugging_face(config["modelos"]["embedding"]):
        return carregar_embedder_local(config["modelos"]["embedding"])
    return BedrockEmbeddings(
        model_id=config["modelos"]["embedding"],
        region_name=config["modelos"]["regiao"],
        model_kwargs={"input_type": tipo_entrada},
        config=Config(retries={"mode": "standard", "total_max_attempts": TENTATIVAS_EMBEDDING}),
    )


def imprimir_progresso(feitos: int, total: int, documento: str) -> None:
    print(f"{feitos / total:.0%} ({feitos}/{total}) {documento}")


def construir(
    config: dict,
    fonte: str,
    limite: int | None = None,
    ao_avancar: Callable[[int, int, str], None] = imprimir_progresso,
) -> int:
    """Chama ao_avancar(chunks feitos, total de chunks, titulo do documento) a cada lote."""
    divisor = criar_divisor(fonte, config)
    colecao = Chroma(
        collection_name=COLECOES[fonte],
        persist_directory=config["caminhos"]["indice"],
        embedding_function=obter_embedder(config, "search_document"),
    )
    documentos = islice(ler_documentos(config, fonte).values(), limite)
    chunks = [chunk for documento in documentos for chunk in chunks_de(documento, divisor)]
    colecao.reset_collection()
    local = eh_hugging_face(config["modelos"]["embedding"])
    feitos = 0
    for lote in batched(chunks, LOTE_EMBEDDING):
        inicio = time.monotonic()
        colecao.add_documents(list(lote))
        if not local:
            intervalo = sum(len(chunk.page_content) for chunk in lote) / CARACTERES_POR_SEGUNDO_EMBEDDING
            time.sleep(max(0, intervalo - (time.monotonic() - inicio)))
        feitos += len(lote)
        ao_avancar(feitos, len(chunks), lote[-1].metadata["titulo"])
    return feitos


def principal() -> None:
    analisador = argparse.ArgumentParser(description="Constroi o indice Chroma a partir de base/")
    analisador.add_argument("--fonte", choices=sorted(COLECOES), required=True)
    analisador.add_argument("--limite", type=int)
    analisador.add_argument("--config", default="config.yaml")
    argumentos = analisador.parse_args()

    config = carregar_config(argumentos.config)
    total = construir(config, argumentos.fonte, limite=argumentos.limite)
    print(f"chunks indexados em {COLECOES[argumentos.fonte]}: {total}")


if __name__ == "__main__":
    principal()
