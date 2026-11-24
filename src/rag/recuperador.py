import argparse
from dataclasses import dataclass
from functools import cache

from langchain_aws import BedrockRerank
from langchain_chroma import Chroma
from langchain_core.documents import Document as DocumentoLangchain

from src.configuracao import carregar_config
from src.ingestao.construir_indice import COLECOES, eh_hugging_face, obter_embedder


@dataclass
class Trecho:
    doc_id: str
    fonte: str
    citacao: str
    metodo_ementa: str
    trecho: str
    score_rerank: float = 0.0
    score_busca: float = 0.0


def reordenar_no_bedrock(config: dict):
    arn = (
        f"arn:aws:bedrock:{config['modelos']['regiao']}::"
        f"foundation-model/{config['modelos']['rerank']}"
    )
    cliente = BedrockRerank(model_arn=arn, region_name=config["modelos"]["regiao"])

    def reordenar(pergunta: str, trechos: list[Trecho]) -> list[tuple[int, float]]:
        saida = cliente.rerank(
            documents=[DocumentoLangchain(page_content=trecho.trecho) for trecho in trechos],
            query=pergunta,
            top_n=len(trechos),
        )
        return [(item["index"], item["relevance_score"]) for item in saida]

    return reordenar


@cache
def carregar_reordenador_local(modelo: str):
    """Importa aqui porque o torch atrasa em segundos qualquer comando que nao use Hugging Face."""
    from sentence_transformers import CrossEncoder

    return CrossEncoder(modelo)


def reordenar_localmente(config: dict):
    modelo = carregar_reordenador_local(config["modelos"]["rerank_hf"])

    def reordenar(pergunta: str, trechos: list[Trecho]) -> list[tuple[int, float]]:
        saida = modelo.rank(pergunta, [trecho.trecho for trecho in trechos])
        return [(item["corpus_id"], float(item["score"])) for item in saida]

    return reordenar


def obter_reordenador(config: dict):
    """Indice do Hugging Face reordena localmente; assim a busca inteira dispensa AWS."""
    if eh_hugging_face(config["modelos"]["embedding"]):
        return reordenar_localmente(config)
    return reordenar_no_bedrock(config)


def aplicar_piso(ordenados: list[Trecho], top_k: int, piso: int) -> list[Trecho]:
    escolhidos = ordenados[:top_k]
    for fonte in COLECOES:
        while sum(trecho.fonte == fonte for trecho in escolhidos) < piso:
            reserva = next(
                (
                    trecho
                    for trecho in ordenados
                    if trecho.fonte == fonte and trecho not in escolhidos
                ),
                None,
            )
            descartavel = next(
                (trecho for trecho in reversed(escolhidos) if trecho.fonte != fonte), None
            )
            if reserva is None or descartavel is None:
                break
            escolhidos.remove(descartavel)
            escolhidos.append(reserva)
    return sorted(escolhidos, key=lambda trecho: trecho.score_rerank, reverse=True)


class Recuperador:
    def __init__(self, config: dict, embedder=None, reordenador=None):
        self.config = config
        self.embedder = embedder or obter_embedder(config, "search_query")
        self.reordenar = reordenador or obter_reordenador(config)
        self.colecoes = {
            fonte: Chroma(
                collection_name=nome,
                persist_directory=config["caminhos"]["indice"],
                embedding_function=self.embedder,
            )
            for fonte, nome in COLECOES.items()
        }

    def buscar_candidatos(self, pergunta: str) -> list[Trecho]:
        cotas = {
            "cjf": self.config["recuperacao"]["candidatos_jurisprudencia"],
            "legislacao": self.config["recuperacao"]["candidatos_legislacao"],
        }
        candidatos: list[Trecho] = []
        vistos: set[str] = set()
        for fonte, cota in cotas.items():
            for encontrado, distancia in self.colecoes[fonte].similarity_search_with_score(
                pergunta, k=cota
            ):
                if encontrado.page_content in vistos:
                    continue
                vistos.add(encontrado.page_content)
                metadados = encontrado.metadata
                candidatos.append(
                    Trecho(
                        doc_id=metadados["doc_id"],
                        fonte=metadados["fonte"],
                        citacao=metadados.get("citacao", metadados.get("titulo", "")),
                        metodo_ementa=metadados.get("metodo_ementa", ""),
                        trecho=encontrado.page_content,
                        score_busca=float(distancia),
                    )
                )
        return candidatos

    def ordenar(self, pergunta: str) -> list[Trecho]:
        candidatos = self.buscar_candidatos(pergunta)
        if not candidatos:
            return []
        for indice, score in self.reordenar(pergunta, candidatos):
            candidatos[indice].score_rerank = score
        return sorted(candidatos, key=lambda trecho: trecho.score_rerank, reverse=True)

    def recuperar(self, pergunta: str) -> list[Trecho]:
        return aplicar_piso(
            self.ordenar(pergunta),
            self.config["recuperacao"]["top_k"],
            self.config["recuperacao"]["piso_por_fonte"],
        )


def principal() -> None:
    analisador = argparse.ArgumentParser(description="Busca sem LLM, para diagnostico")
    analisador.add_argument("pergunta")
    analisador.add_argument("--config", default="config.yaml")
    argumentos = analisador.parse_args()

    recuperador = Recuperador(carregar_config(argumentos.config))
    for trecho in recuperador.recuperar(argumentos.pergunta):
        print(
            f"[{trecho.fonte}] {trecho.score_rerank:.3f} "
            f"{trecho.citacao} ({trecho.metodo_ementa})"
        )
        print(trecho.trecho[:300].replace("\n", " "))
        print("-" * 70)


if __name__ == "__main__":
    principal()
