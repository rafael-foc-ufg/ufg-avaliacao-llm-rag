import csv
import re
import unicodedata
from collections.abc import Iterator
from functools import cache
from pathlib import Path

from src.ingestao.modelo import (
    Documento,
    formatar_processo,
    montar_citacao,
    sigla_classe,
    sigla_tribunal,
)

csv.field_size_limit(10**9)

MINIMO_DECISAO = 500
LIMITE_EMENTA = 6000
LIMITE_FALLBACK = 2500
LIMITE_TRUNCADO_ORIGEM = 32700

INICIO_EMENTA = re.compile(r"E\s+M\s+E\s+N\s+T\s+A|\bEMENTA\b")
FIM_EMENTA = re.compile(
    r"R\s+E\s+L\s+A\s+T\s+[OÓ]\s+R\s+I\s+O|\bRELAT[OÓ]RIO\b"
    r"|V\s+O\s+T\s+O|\bVOTO\b"
    r"|A\s+C\s+[OÓ]\s+R\s+D\s+[AÃ]\s+O|\bAC[OÓ]RD[AÃ]O\b"
)
FIM_AUTUACAO = re.compile(r"OUTROS\s+PARTICIPANTES:")
INICIO_CONTEUDO = re.compile(
    r"R\s+E\s+L\s+A\s+T\s+[OÓ]\s+R\s+I\s+O|\bRELAT[OÓ]RIO\b"
    r"|V\s+O\s+T\s+O|\bVOTO\b"
    r"|D\s+E\s+C\s+I\s+S\s+[AÃ]\s+O|\bDECIS[AÃ]O\b"
    r"|\bTrata-se\b|\bVistos\b"
)

TERMOS_TEMA = (
    "pensao", "dependente", "companheir", "uniao estavel",
    "obito", "segurado", "conjuge", "viuv",
)


def sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(letra for letra in decomposto if not unicodedata.combining(letra))


def extrair_ementa(decisao: str) -> tuple[str, str]:
    inicio = INICIO_EMENTA.search(decisao)
    if inicio:
        corpo = decisao[inicio.end():]
        fim = FIM_EMENTA.search(corpo)
        recorte = corpo[: fim.start()] if fim else corpo
        return recorte.strip()[:LIMITE_EMENTA], "marcador"
    return inicio_do_conteudo(decisao).strip()[:LIMITE_FALLBACK], "fallback"


def inicio_do_conteudo(decisao: str) -> str:
    """O cabecalho do TRF vem repetido antes do corpo, entao ancora na ultima
    autuacao e nao na primeira; sem autuacao, cai no marcador de relatorio."""
    autuacoes = list(FIM_AUTUACAO.finditer(decisao))
    if autuacoes:
        return decisao[autuacoes[-1].end():]
    conteudo = INICIO_CONTEUDO.search(decisao)
    return decisao[conteudo.start():] if conteudo else decisao


def trata_do_tema(texto: str) -> bool:
    normalizado = sem_acento(texto).lower()
    return any(termo in normalizado for termo in TERMOS_TEMA)


def converter(registro: dict) -> Documento | None:
    decisao = registro["DECISÃO COMPLETA"]
    if len(decisao) < MINIMO_DECISAO:
        return None
    texto, metodo = extrair_ementa(decisao)
    if not trata_do_tema(texto):
        return None
    processo = formatar_processo(registro["PROCESSO JUDICIAL"])
    meta = {
        "tribunal": sigla_tribunal(registro["TRIBUNAL"]),
        "turma": registro["TURMA"],
        "julgador": registro["JULGADOR"],
        "classe": sigla_classe(registro["CLASSE"]),
        "processo": processo,
        "data_publicacao": registro["DATA PUBLICAÇÃO"][:10],
        "metodo_ementa": metodo,
        "truncado_origem": len(decisao) >= LIMITE_TRUNCADO_ORIGEM,
    }
    meta["citacao"] = montar_citacao(meta)
    return Documento(
        doc_id=processo,
        fonte="cjf",
        titulo=meta["citacao"],
        texto=texto,
        meta=meta,
    )


def ler_csv(caminho: Path) -> Iterator[Documento]:
    with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
        for registro in csv.DictReader(arquivo):
            documento = converter(registro)
            if documento:
                yield documento


def ler_diretorio(diretorio: Path) -> Iterator[Documento]:
    for caminho in sorted(diretorio.glob("*.csv")):
        yield from ler_csv(caminho)


@cache
def ler_processos(diretorio: Path) -> frozenset[str]:
    """Digitos de todo processo dos CSVs, inclusive os fora do tema: todos existem de fato."""
    processos = set()
    for caminho in sorted(diretorio.glob("*.csv")):
        with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
            processos.update(
                re.sub(r"\D", "", formatar_processo(registro["PROCESSO JUDICIAL"]))
                for registro in csv.DictReader(arquivo)
            )
    return frozenset(processos)
