import re
import statistics
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from groq import BadRequestError
from langchain_aws import ChatBedrockConverse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel

from src.avaliacao.datajud import extrair_numeros_cnj, verificar_processos
from src.ingestao.cjf import ler_processos


AVALIACOES = 3
Situacao = Literal["confirmada", "contradita", "nao_verificavel"]
ACERTO = {"fidelidade": "confirmada", "precisao": "correta", "completude": "presente"}
FALHA = {"fidelidade": "contradita", "precisao": "incorreta", "completude": "faltou"}


class Citacao(BaseModel):
    texto: str
    numero_cnj: str
    situacao: Situacao
    motivo: str


class Afirmacao(BaseModel):
    texto: str
    correta: bool
    motivo: str


class Ponto(BaseModel):
    atendido: bool
    motivo: str


class Veredito(BaseModel):
    citacoes: list[Citacao]
    tese_correta: bool
    motivo_tese: str
    sentimento: Literal["positivo", "negativo", "ausente"]
    motivo_sentimento: str
    afirmacoes: list[Afirmacao]
    pontos: list[Ponto]
    decisoes: list[str]


@dataclass
class Item:
    texto: str
    situacao: str
    motivo: str
    destaque: bool = False


@dataclass
class Fracao:
    acertos: int
    total: int

    @property
    def valor(self) -> float | None:
        return self.acertos / self.total if self.total else None


@dataclass
class Pontuacao:
    fidelidade: Fracao
    precisao: Fracao
    completude: Fracao

    @property
    def nota(self) -> float:
        valores = [fracao.valor for fracao in (self.fidelidade, self.precisao, self.completude)]
        return round(statistics.mean(valor for valor in valores if valor is not None) * 10, 2)


@dataclass
class Julgado:
    vereditos: list[Veredito]
    latencia_ms: int
    tokens_entrada: int
    tokens_saida: int
    processos: dict[str, str]


def numerar(itens: list[str]) -> str:
    return "\n".join(f"{numero}. {item}" for numero, item in enumerate(itens, start=1)) or "(nenhum)"


def carregar_prompt(config: dict) -> str:
    return Path(config["caminhos"]["prompt_juiz"]).read_text(encoding="utf-8").strip()


def montar_mensagens(prompt: str, questao: dict, resposta: str, processos: dict[str, str]) -> list[BaseMessage]:
    """Avaliacao as cegas: as mensagens nao revelam se a resposta usou RAG."""
    gabarito = "\n\n".join(
        [
            f"PERGUNTA:\n{questao['pergunta']}",
            f"RESPOSTA ESPERADA:\n{questao['resposta_esperada']}",
            f"SENTIMENTO ESPERADO: {questao['sentimento_esperado']}",
            f"EMENTAS ESPERADAS:\n{numerar(questao['ementas_esperadas'])}",
            f"REFERENCIAS:\n{numerar(questao['referencias'])}",
            f"PONTOS OBRIGATORIOS:\n{numerar(questao['pontos_obrigatorios'])}",
            f"INACEITAVEL:\n{numerar(questao['inaceitavel'])}",
            f"OBSERVACAO:\n{questao.get('observacao') or '(nenhuma)'}",
        ]
    )
    verificados = numerar([f"{numero}: {situacao}" for numero, situacao in processos.items()])
    return [
        SystemMessage(content=prompt),
        HumanMessage(
            content=f"DATA DA AVALIACAO: {date.today():%d/%m/%Y}\n\nGABARITO\n\n{gabarito}\n\nRESPOSTA A AVALIAR:\n{resposta}"
            f"\n\nPROCESSOS CITADOS NA RESPOSTA (verificacao na base CJF e no DataJud):\n{verificados}"
        ),
    ]


def digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def numeros_da_citacao(citacao: Citacao) -> list[str]:
    return [citacao.numero_cnj] if citacao.numero_cnj else extrair_numeros_cnj(citacao.texto)


def ajustar_citacoes(citacoes: list[Citacao], questao: dict, processos: dict[str, str]) -> list[Citacao]:
    """Corrige o juiz com o DataJud; inexistentes nao citados entram como contraditas no fim."""
    situacoes = {digitos(numero): situacao for numero, situacao in processos.items()}
    gabarito = [digitos(texto) for texto in questao["ementas_esperadas"] + questao["referencias"]]
    ajustadas = []
    citados = set()
    for citacao in citacoes:
        numeros = [digitos(numero) for numero in numeros_da_citacao(citacao)]
        citados.update(numeros)
        consultadas = [situacoes.get(numero) for numero in numeros]
        if "inexistente" in consultadas:
            citacao = citacao.model_copy(update={"situacao": FALHA["fidelidade"]})
        elif (
            "nao_verificado" in consultadas
            and citacao.situacao == ACERTO["fidelidade"]
            and not any(numero in item for numero in numeros for item in gabarito)
        ):
            citacao = citacao.model_copy(update={"situacao": "nao_verificavel"})
        ajustadas.append(citacao)
    for numero, situacao in processos.items():
        if situacao == "inexistente" and digitos(numero) not in citados:
            ajustadas.append(
                Citacao(texto=numero, numero_cnj=numero, situacao=FALHA["fidelidade"], motivo="processo inexistente no DataJud")
            )
    return ajustadas


def itens_fidelidade(veredito: Veredito, questao: dict, processos: dict[str, str]) -> list[Item]:
    citacoes = ajustar_citacoes(veredito.citacoes, questao, processos)
    return [Item(citacao.texto, citacao.situacao, citacao.motivo) for citacao in citacoes]


def avaliar_item(texto: str, certo: bool, motivo: str, criterio: str, destaque: bool = False) -> Item:
    return Item(texto, ACERTO[criterio] if certo else FALHA[criterio], motivo, destaque)


def sentimento_confere(sentimento: str, esperado: str) -> bool:
    """Com esperado positivo_ou_negativo, o caso admite os dois desfechos e qualquer um esta correto."""
    if esperado == "positivo_ou_negativo":
        return sentimento in ("positivo", "negativo")
    return sentimento == esperado


def itens_precisao(veredito: Veredito, questao: dict) -> list[Item]:
    """Sentimento ausente nao entra aqui: so falta na completude."""
    esperado = questao["sentimento_esperado"]
    itens = [avaliar_item("Tese", veredito.tese_correta, veredito.motivo_tese, "precisao", destaque=True)]
    if veredito.sentimento != "ausente":
        itens.append(
            avaliar_item(
                f"Sentimento: {veredito.sentimento} (esperado: {esperado})",
                sentimento_confere(veredito.sentimento, esperado),
                veredito.motivo_sentimento,
                "precisao",
            )
        )
    itens += [avaliar_item(a.texto, a.correta, a.motivo, "precisao") for a in veredito.afirmacoes]
    return itens


def item_decisoes(veredito: Veredito, processos: dict[str, str]) -> Item:
    """Numero nao_verificado nao conta nem desconta: se so com ele a cota fecha, o item fica fora da fracao."""
    situacoes = {digitos(numero): situacao for numero, situacao in processos.items()}
    decisoes = {
        digitos(numero) for decisao in veredito.decisoes for numero in extrair_numeros_cnj(decisao) or [decisao]
    } - {""}
    validas = {numero for numero in decisoes if situacoes.get(numero) not in ("inexistente", "nao_verificado")}
    pendentes = {numero for numero in decisoes if situacoes.get(numero) == "nao_verificado"}
    texto = "3 decisões com número e ementa"
    if len(validas) < 3 <= len(validas) + len(pendentes):
        return Item(texto, "nao_verificavel", f"{len(validas)} válidas e {len(pendentes)} sem verificação no DataJud")
    return avaliar_item(texto, len(validas) >= 3, f"{len(validas)} válidas", "completude")


def itens_completude(veredito: Veredito, questao: dict, processos: dict[str, str]) -> list[Item]:
    itens = []
    for posicao, texto in enumerate(questao["pontos_obrigatorios"]):
        if posicao < len(veredito.pontos):
            ponto = veredito.pontos[posicao]
            itens.append(avaliar_item(texto, ponto.atendido, ponto.motivo, "completude"))
        else:
            itens.append(Item(texto, FALHA["completude"], "não avaliado pelo juiz"))
    itens.append(item_decisoes(veredito, processos))
    itens.append(
        avaliar_item("Indicação do sentimento", veredito.sentimento != "ausente", veredito.motivo_sentimento, "completude")
    )
    return itens


def fracionar(itens: list[Item], criterio: str) -> Fracao:
    return Fracao(
        sum(item.situacao == ACERTO[criterio] for item in itens),
        sum(item.situacao in (ACERTO[criterio], FALHA[criterio]) for item in itens),
    )


def pontuar(veredito: Veredito, questao: dict, processos: dict[str, str]) -> Pontuacao:
    return Pontuacao(
        fidelidade=fracionar(itens_fidelidade(veredito, questao, processos), "fidelidade"),
        precisao=fracionar(itens_precisao(veredito, questao), "precisao"),
        completude=fracionar(itens_completude(veredito, questao, processos), "completude"),
    )


def escolher_mediana(pontuacoes: list[Pontuacao]) -> int:
    notas = [pontuacao.nota for pontuacao in pontuacoes]
    return notas.index(statistics.median(notas))


def obter_llm_juiz(config: dict) -> BaseChatModel:
    """Sem temperatura: o modelo juiz do Bedrock a rejeita como parametro obsoleto.
    No Groq, as retentativas esperam o limite de tokens por minuto liberar."""
    if config["provedor"] == "groq":
        return ChatGroq(
            model=config["modelos"]["juiz_groq"],
            max_tokens=config["geracao"]["max_tokens_juiz"],
            reasoning_effort=config["geracao"]["raciocinio_juiz_groq"] or None,
            max_retries=6,
        )
    return ChatBedrockConverse(
        model=config["modelos"]["juiz"],
        region_name=config["modelos"]["regiao"],
        max_tokens=config["geracao"]["max_tokens_juiz"],
    )


class Juiz:
    def __init__(self, config: dict):
        self.modelo = config["modelos"]["juiz_groq" if config["provedor"] == "groq" else "juiz"]
        self.prompt = carregar_prompt(config)
        self.url_datajud = config["datajud"]["url"]
        self.processos_base = ler_processos(Path(config["caminhos"]["base_cjf"]))
        llm = obter_llm_juiz(config)
        if config["provedor"] == "groq":
            self.llm = llm.with_structured_output(
                Veredito, method="json_schema", include_raw=True, strict=True
            ).with_retry(retry_if_exception_type=(BadRequestError,), stop_after_attempt=3)
        else:
            self.llm = llm.with_structured_output(Veredito, method="json_schema", include_raw=True)

    def avaliar(self, questao: dict, resposta: str) -> Julgado:
        processos = verificar_processos(resposta, self.url_datajud, self.processos_base)
        vereditos = []
        latencia_ms = tokens_entrada = tokens_saida = 0
        for _ in range(AVALIACOES):
            inicio = time.perf_counter()
            saida = self.llm.invoke(montar_mensagens(self.prompt, questao, resposta, processos))
            latencia_ms += int((time.perf_counter() - inicio) * 1000)
            if saida["parsed"] is None:
                raise ValueError(f"juiz devolveu veredito invalido: {saida['parsing_error']}")
            uso = saida["raw"].usage_metadata or {}
            tokens_entrada += uso.get("input_tokens", 0)
            tokens_saida += uso.get("output_tokens", 0)
            vereditos.append(saida["parsed"])
        return Julgado(vereditos, latencia_ms, tokens_entrada, tokens_saida, processos)
