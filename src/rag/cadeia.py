import time
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.rag.llm import obter_llm
from src.rag.recuperador import Recuperador, Trecho

PROMPT_SISTEMA = """Voce e um assistente juridico especializado em pensao por morte.

1. Responda exclusivamente a partir do CONTEXTO fornecido.
2. Quando o contexto nao cobre a pergunta, declare isso de forma explicita. Nunca
   complete com conhecimento proprio.
3. Cite a fonte de cada afirmacao. Jurisprudencia no formato
   [TRF-3, ApCiv 0000001-67.2022.4.03.9999, 03/03/2023]; legislacao no formato
   [Lei 8.213/91, art. 74].
4. Distinga o que e norma do que e entendimento jurisprudencial.
5. Trecho marcado como metodo_ementa: fallback e relato de caso, nao tese firmada.
   Pode ser citado como exemplo, nunca como entendimento do tribunal.
6. O que vem depois de [REVOGADO], ate o fim da linha, e redacao superada. Nao a
   apresente como norma vigente. Use-a apenas para fatos ocorridos durante a sua
   vigencia e diga que foi revogada."""


@dataclass
class Resposta:
    texto: str
    trechos: list[Trecho]
    latencia_ms: int
    tokens_entrada: int
    tokens_saida: int


def montar_contexto(trechos: list[Trecho]) -> str:
    blocos = []
    for numero, trecho in enumerate(trechos, start=1):
        cabecalho = f"[{numero}] fonte: {trecho.fonte} | citacao: {trecho.citacao}"
        if trecho.fonte == "cjf":
            cabecalho += f" | metodo_ementa: {trecho.metodo_ementa}"
        blocos.append(f"{cabecalho}\n{trecho.trecho}")
    return "\n\n".join(blocos)


def montar_resposta(saida: AIMessage, trechos: list[Trecho], inicio: float) -> Resposta:
    uso = saida.usage_metadata or {}
    return Resposta(
        texto=str(saida.text),
        trechos=trechos,
        latencia_ms=int((time.perf_counter() - inicio) * 1000),
        tokens_entrada=uso.get("input_tokens", 0),
        tokens_saida=uso.get("output_tokens", 0),
    )


class Direto:
    def __init__(self, config: dict):
        self.llm = obter_llm(config)

    def responder(self, pergunta: str) -> Resposta:
        inicio = time.perf_counter()
        saida = self.llm.invoke([HumanMessage(content=pergunta)])
        return montar_resposta(saida, [], inicio)


class Cadeia:
    def __init__(self, config: dict):
        self.recuperador = Recuperador(config)
        self.llm = obter_llm(config)

    def montar_mensagens(self, pergunta: str, trechos: list[Trecho]) -> list[BaseMessage]:
        contexto = montar_contexto(trechos)
        return [
            SystemMessage(content=PROMPT_SISTEMA),
            HumanMessage(content=f"CONTEXTO:\n{contexto}\n\nPERGUNTA: {pergunta}"),
        ]

    def responder(self, pergunta: str) -> Resposta:
        inicio = time.perf_counter()
        trechos = self.recuperador.recuperar(pergunta)
        saida = self.llm.invoke(self.montar_mensagens(pergunta, trechos))
        return montar_resposta(saida, trechos, inicio)
