import copy
from dataclasses import asdict
import statistics
from datetime import datetime
from itertools import islice
from pathlib import Path

from django.db import models

from src.ingestao.cjf import ler_processos
from src.ingestao.construir_indice import COLECOES, chunks_de, criar_divisor, ler_documentos
from src.avaliacao.datajud import verificar_processos
from src.avaliacao.juiz import (
    Pontuacao,
    Veredito,
    digitos,
    escolher_mediana,
    itens_completude,
    itens_fidelidade,
    itens_precisao,
    pontuar,
)
from src.rag.cadeia import Resposta


def gerar_nome(prefixo: str, agora: datetime) -> str:
    return f"{prefixo}-{agora:%Y-%m-%d-%H-%M}"


def medir_chunks(config: dict, limite: int | None) -> dict:
    """Devolve por fonte: chunks, caracteres, tam_min, tam_mediana e tam_max."""
    medidas = {}
    for fonte in COLECOES:
        divisor = criar_divisor(fonte, config)
        documentos = islice(ler_documentos(config, fonte).values(), limite)
        tamanhos = [
            len(chunk.page_content)
            for documento in documentos
            for chunk in chunks_de(documento, divisor)
        ]
        medidas[fonte] = {
            "chunks": len(tamanhos),
            "caracteres": sum(tamanhos),
            "tam_min": min(tamanhos),
            "tam_mediana": statistics.median(tamanhos),
            "tam_max": max(tamanhos),
        }
    return medidas


class Indice(models.Model):
    class Status(models.TextChoices):
        CONSTRUINDO = "construindo", "Construindo"
        PRONTO = "pronto", "Pronto"
        FALHOU = "falhou", "Falhou"

    nome = models.CharField("nome", max_length=100, unique=True)
    status = models.CharField("situação", max_length=20, choices=Status, default=Status.CONSTRUINDO)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    tamanho = models.PositiveIntegerField("tamanho do chunk")
    overlap = models.PositiveIntegerField("sobreposição")
    embedding = models.CharField("modelo de embedding", max_length=100)
    limite = models.PositiveIntegerField("limite de documentos", null=True, blank=True)
    estatisticas = models.JSONField("estatísticas", default=dict)
    progresso = models.JSONField("progresso", default=dict)
    erro = models.TextField("erro", blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "índice"
        verbose_name_plural = "índices"

    def __str__(self) -> str:
        return self.nome

    @property
    def total_chunks(self) -> int:
        return sum(medida["chunks"] for medida in self.estatisticas.values())

    def pasta(self, config: dict) -> Path:
        return Path(config["caminhos"]["indices"]) / self.nome

    def config_aplicada(self, config: dict) -> dict:
        """Devolve uma copia do config com os parametros deste indice."""
        aplicada = copy.deepcopy(config)
        aplicada["caminhos"]["indice"] = self.pasta(config).as_posix()
        aplicada["modelos"]["embedding"] = self.embedding
        aplicada["chunking"] = {"tamanho": self.tamanho, "overlap": self.overlap}
        return aplicada


class Rodada(models.Model):
    class Status(models.TextChoices):
        EXECUTANDO = "executando", "Executando"
        CONCLUIDA = "concluida", "Concluída"
        FALHOU = "falhou", "Falhou"

    class StatusAvaliacao(models.TextChoices):
        PENDENTE = "pendente", "Não avaliada"
        AVALIANDO = "avaliando", "Avaliando"
        CONCLUIDA = "concluida", "Avaliada"
        FALHOU = "falhou", "Avaliação falhou"

    criada_em = models.DateTimeField("criada em", auto_now_add=True)
    indice = models.ForeignKey(Indice, on_delete=models.PROTECT, verbose_name="índice", related_name="rodadas")
    status = models.CharField("situação", max_length=20, choices=Status, default=Status.EXECUTANDO)
    total = models.PositiveIntegerField("total de respostas")
    config = models.JSONField("configuração", default=dict)
    erro = models.TextField("erro", blank=True)
    status_avaliacao = models.CharField(
        "situação da avaliação", max_length=20, choices=StatusAvaliacao, default=StatusAvaliacao.PENDENTE
    )
    erro_avaliacao = models.TextField("erro da avaliação", blank=True)

    class Meta:
        ordering = ["-criada_em"]
        verbose_name = "rodada"
        verbose_name_plural = "rodadas"

    def julgamentos(self) -> list[int]:
        return sorted(set(Avaliacao.objects.filter(execucao__rodada=self).values_list("julgamento", flat=True)))


class Execucao(models.Model):
    criada_em = models.DateTimeField("criada em", auto_now_add=True)
    pergunta = models.TextField("pergunta")
    indice = models.ForeignKey(
        Indice, null=True, on_delete=models.PROTECT, verbose_name="índice", related_name="execucoes"
    )
    rodada = models.ForeignKey(
        Rodada, null=True, on_delete=models.CASCADE, verbose_name="rodada", related_name="execucoes"
    )
    questao = models.ForeignKey(
        "Questao", null=True, on_delete=models.SET_NULL, verbose_name="questão", related_name="execucoes"
    )
    config = models.JSONField("configuração")
    trechos = models.JSONField("trechos")
    resposta = models.TextField("resposta")
    latencia_ms = models.PositiveIntegerField("latência (ms)")
    tokens_entrada = models.PositiveIntegerField("tokens de entrada", default=0)
    tokens_saida = models.PositiveIntegerField("tokens de saída", default=0)

    class Meta:
        ordering = ["-criada_em"]
        verbose_name = "execução"
        verbose_name_plural = "execuções"


def registrar_execucao(
    resposta: Resposta, pergunta: str, indice: Indice | None, config: dict, **vinculos
) -> Execucao:
    return Execucao.objects.create(
        pergunta=pergunta,
        indice=indice,
        config=config,
        trechos=[asdict(trecho) for trecho in resposta.trechos],
        resposta=resposta.texto,
        latencia_ms=resposta.latencia_ms,
        tokens_entrada=resposta.tokens_entrada,
        tokens_saida=resposta.tokens_saida,
        **vinculos,
    )


class Questao(models.Model):
    class Sentimento(models.TextChoices):
        POSITIVO = "positivo", "Positivo"
        NEGATIVO = "negativo", "Negativo"
        POSITIVO_OU_NEGATIVO = "positivo_ou_negativo", "Positivo ou negativo"

    codigo = models.CharField("código", max_length=20, unique=True)
    numero = models.PositiveIntegerField("número", unique=True)
    titulo = models.CharField("título", max_length=200)
    pergunta = models.TextField("pergunta")
    resposta_esperada = models.TextField("resposta esperada")
    sentimento_esperado = models.CharField("sentimento esperado", max_length=20, choices=Sentimento)
    ementas_esperadas = models.JSONField("ementas esperadas", default=list)
    referencias = models.JSONField("referências", default=list, blank=True)
    pontos_obrigatorios = models.JSONField("pontos obrigatórios", default=list, blank=True)
    inaceitavel = models.JSONField("inaceitável", default=list, blank=True)
    observacao = models.TextField("observação", blank=True)

    class Meta:
        ordering = ["numero"]
        verbose_name = "questão"
        verbose_name_plural = "questões"

    def __str__(self) -> str:
        return f"{self.codigo} {self.titulo}"

    def como_gabarito(self) -> dict:
        """Somente os campos que o juiz pode ver."""
        return {
            "pergunta": self.pergunta,
            "resposta_esperada": self.resposta_esperada,
            "sentimento_esperado": self.sentimento_esperado,
            "ementas_esperadas": self.ementas_esperadas,
            "referencias": self.referencias,
            "pontos_obrigatorios": self.pontos_obrigatorios,
            "inaceitavel": self.inaceitavel,
            "observacao": self.observacao,
        }


class Avaliacao(models.Model):
    criada_em = models.DateTimeField("criada em", auto_now_add=True)
    execucao = models.ForeignKey(
        Execucao, on_delete=models.CASCADE, verbose_name="execução", related_name="avaliacoes"
    )
    julgamento = models.PositiveSmallIntegerField("julgamento", default=1)
    modelo = models.CharField("modelo juiz", max_length=100)
    prompt = models.TextField("prompt do juiz", blank=True)
    gabarito = models.JSONField("gabarito enviado ao juiz")
    vereditos = models.JSONField("vereditos do juiz")
    mediana = models.PositiveSmallIntegerField("avaliação mediana")
    fidelidade = models.FloatField("fidelidade", null=True)
    precisao = models.FloatField("precisão")
    completude = models.FloatField("completude")
    amplitude = models.FloatField("amplitude da nota")
    nota = models.FloatField("nota")
    latencia_ms = models.PositiveIntegerField("latência (ms)")
    tokens_entrada = models.PositiveIntegerField("tokens de entrada", default=0)
    tokens_saida = models.PositiveIntegerField("tokens de saída", default=0)
    processos = models.JSONField("processos citados no DataJud", default=dict)

    class Meta:
        ordering = ["-criada_em"]
        verbose_name = "avaliação"
        verbose_name_plural = "avaliações"
        constraints = [
            models.UniqueConstraint(fields=["execucao", "julgamento"], name="uma_avaliacao_por_julgamento")
        ]

    @property
    def tese_correta(self) -> bool:
        return self.vereditos[self.mediana]["tese_correta"]

    def pontuacoes(self) -> list[Pontuacao]:
        return [pontuar(Veredito.model_validate(v), self.gabarito, self.processos) for v in self.vereditos]

    def pontuar(self) -> None:
        """Recalcula mediana e notas a partir de vereditos e processos, sem chamar o juiz."""
        pontuacoes = self.pontuacoes()
        notas = [pontuacao.nota for pontuacao in pontuacoes]
        self.mediana = escolher_mediana(pontuacoes)
        escolhida = pontuacoes[self.mediana]
        self.fidelidade = escolhida.fidelidade.valor
        self.precisao = escolhida.precisao.valor
        self.completude = escolhida.completude.valor
        self.amplitude = max(notas) - min(notas)
        self.nota = escolhida.nota

    @property
    def verificada(self) -> bool:
        return "nao_verificado" not in self.processos.values()

    def blocos(self) -> dict[str, dict]:
        """Itens e fracao da avaliacao mediana; valores do criterio nas tres avaliacoes."""
        pontuacoes = self.pontuacoes()
        mediana = Veredito.model_validate(self.vereditos[self.mediana])
        itens = {
            "fidelidade": itens_fidelidade(mediana, self.gabarito, self.processos),
            "precisao": itens_precisao(mediana, self.gabarito),
            "completude": itens_completude(mediana, self.gabarito, self.processos),
        }
        return {
            criterio: {
                "fracao": getattr(pontuacoes[self.mediana], criterio),
                "valores": [getattr(p, criterio).valor for p in pontuacoes],
                "itens": itens[criterio],
            }
            for criterio in itens
        }


SISTEMAS = (("com_rag", "LLM com RAG"), ("sem_rag", "LLM Padrão"))


def media(valores: list[float | None]) -> float | None:
    validos = [valor for valor in valores if valor is not None]
    return statistics.mean(validos) if validos else None


def placar(rodada: Rodada, julgamento: int) -> list[dict]:
    """Uma linha por sistema. A origem de cada resposta so e lida aqui, depois do juiz."""
    avaliacoes = {chave: [] for chave, _ in SISTEMAS}
    for avaliacao in Avaliacao.objects.filter(execucao__rodada=rodada, julgamento=julgamento).select_related("execucao"):
        avaliacoes["com_rag" if avaliacao.execucao.indice_id else "sem_rag"].append(avaliacao)
    return [
        {
            "rotulo": rotulo,
            "avaliadas": len(avaliacoes[chave]),
            "fidelidade_media": media([a.fidelidade for a in avaliacoes[chave]]),
            "com_fidelidade": sum(a.fidelidade is not None for a in avaliacoes[chave]),
            "teses_corretas": sum(a.tese_correta for a in avaliacoes[chave]),
            "precisao_media": media([a.precisao for a in avaliacoes[chave]]),
            "completude_media": media([a.completude for a in avaliacoes[chave]]),
            "nota_media": media([a.nota for a in avaliacoes[chave]]),
            "amplitude_media": media([a.amplitude for a in avaliacoes[chave]]),
        }
        for chave, rotulo in SISTEMAS
    ]


def delta_verificado(rodada: Rodada, julgamento: int) -> tuple[float | None, int]:
    """Delta medio da nota so nas questoes em que os dois sistemas tiveram todo processo verificado."""
    pares = {}
    for avaliacao in Avaliacao.objects.filter(execucao__rodada=rodada, julgamento=julgamento).select_related("execucao"):
        pares.setdefault(avaliacao.execucao.questao_id, {})[bool(avaliacao.execucao.indice_id)] = avaliacao
    deltas = [
        par[True].nota - par[False].nota
        for par in pares.values()
        if len(par) == 2 and par[True].verificada and par[False].verificada
    ]
    return media(deltas), len(deltas)


def reverificar_processos(rodada: Rodada, config: dict) -> int:
    """Reconsulta os processos nao_verificado da rodada e regrava as notas; devolve quantos seguem pendentes.
    Cada numero e consultado uma vez por chamada, para valer a mesma situacao nos dois sistemas."""
    avaliacoes = list(Avaliacao.objects.filter(execucao__rodada=rodada))
    conhecidas = {
        digitos(numero): situacao
        for avaliacao in avaliacoes
        for numero, situacao in avaliacao.processos.items()
        if situacao != "nao_verificado"
    }
    na_base = ler_processos(Path(config["caminhos"]["base_cjf"]))
    pendentes = 0
    for avaliacao in avaliacoes:
        if avaliacao.verificada:
            continue
        for numero, situacao in avaliacao.processos.items():
            if situacao == "nao_verificado":
                if digitos(numero) not in conhecidas:
                    conhecidas[digitos(numero)] = verificar_processos(numero, config["datajud"]["url"], na_base)[numero]
                avaliacao.processos[numero] = conhecidas[digitos(numero)]
        avaliacao.pontuar()
        avaliacao.save()
        pendentes += list(avaliacao.processos.values()).count("nao_verificado")
    return pendentes
