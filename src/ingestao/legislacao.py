import hashlib
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from bs4.element import Tag

from src.ingestao.modelo import Documento

MINIMO_TEXTO = 500
ARQUIVO_FONTES = "fontes.yaml"

MARCA_REVOGADO = "[REVOGADO]"
QUEBRA = "\x1f"
CONTEUDO = "div.texto-dou, div.col-8.offset-4, div#content-core"
REVOGADOS = "strike, s, del, [style*='line-through' i]"
TAMANHO_TIPOGRAFICO = 2
PREFIXO_DISPOSITIVO = 12
RUIDO = ["script", "style", "noscript"]
BLOCOS = [
    "p", "div", "li", "tr", "td", "table", "center", "br", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
]


def carregar_fontes(diretorio: Path) -> dict:
    return yaml.safe_load((diretorio / ARQUIVO_FONTES).read_text(encoding="utf-8"))


def riscado_tipografico(texto: str) -> bool:
    """O Planalto tambem risca so o ordinal (5<s>o</s>), sem revogar nada."""
    return len(texto) <= TAMANHO_TIPOGRAFICO and not any(c.isdigit() for c in texto)


def marcar_revogados(conteudo: Tag) -> None:
    for trecho in conteudo.select(REVOGADOS):
        if not riscado_tipografico(trecho.get_text(strip=True)):
            for alvo in trecho.find_all(BLOCOS) or [trecho]:
                alvo.insert(0, f"{MARCA_REVOGADO} ")


def separar_blocos(conteudo: Tag) -> None:
    for bloco in conteudo.find_all(BLOCOS):
        bloco.insert_before(QUEBRA)
        bloco.insert_after(QUEBRA)


def limpar_linha(bruta: str) -> str:
    """Fragmentos riscados da mesma linha geram varias marcas; so a primeira fica.
    O risco pode comecar depois do rotulo (A<s>rt. 26</s>): a marca sobe para o inicio."""
    antes, marca, depois = " ".join(bruta.split()).partition(MARCA_REVOGADO)
    depois = depois.replace(MARCA_REVOGADO, "")
    if marca and len(antes) <= PREFIXO_DISPOSITIVO:
        linha = f"{marca} {antes}{depois.lstrip()}"
    else:
        linha = f"{antes}{marca}{depois}"
    linha = " ".join(linha.split())
    return "" if linha == MARCA_REVOGADO else linha


def extrair_texto(caminho: Path) -> str:
    sopa = BeautifulSoup(caminho.read_text(encoding="utf-8"), "html.parser")
    conteudo = sopa.select_one(CONTEUDO) or sopa.body
    for ruido in conteudo.find_all(RUIDO):
        ruido.decompose()
    marcar_revogados(conteudo)
    separar_blocos(conteudo)
    linhas = (limpar_linha(bruta) for bruta in conteudo.get_text().split(QUEBRA))
    return "\n".join(linha for linha in linhas if linha)


def ler_diretorio(diretorio: Path) -> list[Documento]:
    fontes = carregar_fontes(diretorio)
    documentos: list[Documento] = []
    vistos: set[str] = set()
    for caminho in sorted(diretorio.rglob("*.html")):
        texto = extrair_texto(caminho)
        if len(texto.strip()) < MINIMO_TEXTO:
            raise ValueError(
                f"{caminho.name}: {len(texto.strip())} chars extraidos, "
                f"minimo {MINIMO_TEXTO}."
            )
        doc_id = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        if doc_id in vistos:
            continue
        vistos.add(doc_id)
        fonte = fontes[caminho.stem]
        norma = fonte["norma"]
        meta = {
            "arquivo": caminho.name,
            "regime": caminho.parent.name,
            "norma": norma,
            "url": fonte["url"],
            "capturado_em": fonte["capturado_em"],
            "citacao": norma,
        }
        documentos.append(
            Documento(doc_id=doc_id, fonte="legislacao", titulo=norma, texto=texto, meta=meta)
        )
    return documentos
