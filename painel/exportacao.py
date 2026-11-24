from pathlib import Path
from typing import BinaryIO

import pandas as pd
from django.db.models import QuerySet
from django.utils import timezone

from painel.models import Avaliacao, Rodada
from src.avaliacao.juiz import FALHA

ALTURA_LINHA = 15


CRITERIOS = (("fidelidade", "Fidelidade"), ("precisao", "Precisão"), ("completude", "Completude"))


def justificativa(avaliacao: Avaliacao) -> str:
    blocos = avaliacao.blocos()
    falhas = [
        f"{rotulo}: {item.texto}" + (f" ({item.motivo})" if item.motivo else "")
        for criterio, rotulo in CRITERIOS
        for item in blocos[criterio]["itens"]
        if item.situacao == FALHA[criterio]
    ]
    return "; ".join(falhas) or "Sem falhas"


def gravar_planilha(destino: Path | BinaryIO, rodadas: QuerySet[Rodada]) -> int:
    """Grava uma linha por resposta avaliada das rodadas, ordenada por questao; devolve o total de linhas."""
    avaliacoes = list(
        Avaliacao.objects.filter(execucao__rodada__in=rodadas, execucao__questao__isnull=False)
        .select_related("execucao__questao", "execucao__rodada")
        .order_by("execucao__questao__numero", "execucao__rodada__criada_em", "julgamento", "-execucao__indice")
    )
    linhas = [
        {
            "Questão": avaliacao.execucao.questao.codigo,
            "Rodada": timezone.localtime(avaliacao.execucao.rodada.criada_em).strftime("%d/%m/%Y %H:%M"),
            "Julgamento": avaliacao.julgamento,
            "Pergunta": avaliacao.execucao.pergunta,
            "Quem respondeu": "RAG" if avaliacao.execucao.indice_id else "LLM",
            "Resposta": avaliacao.execucao.resposta,
            "Tokens de entrada": avaliacao.execucao.tokens_entrada,
            "Tokens de saída": avaliacao.execucao.tokens_saida,
            "Latência (ms)": avaliacao.execucao.latencia_ms,
            "Nota": avaliacao.nota,
            "Fidelidade": avaliacao.fidelidade,
            "Precisão": avaliacao.precisao,
            "Completude": avaliacao.completude,
            "Tese correta": "Sim" if avaliacao.tese_correta else "Não",
            "Amplitude da nota": avaliacao.amplitude,
            "Processos inexistentes": list(avaliacao.processos.values()).count("inexistente"),
            "Processos não verificados": list(avaliacao.processos.values()).count("nao_verificado"),
            "Justificativa do juiz": justificativa(avaliacao),
        }
        for avaliacao in avaliacoes
    ]
    with pd.ExcelWriter(destino, engine="openpyxl") as planilha:
        pd.DataFrame(linhas).to_excel(planilha, sheet_name="respostas", index=False)
        aba = planilha.sheets["respostas"]
        for numero in range(1, aba.max_row + 1):
            aba.row_dimensions[numero].height = ALTURA_LINHA
    return len(linhas)
